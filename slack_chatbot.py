from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
import openai
import logging
import json
import os
import uvicorn
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

# ---------------------------------------------

app = FastAPI()


class Settings(BaseModel):
    environment: str
    logging_path: str
    users: dict
    slackapi_key: str
    openai_key: str
    mindset: str


def getsettings(filename):
    with open(filename, 'r') as file:
        data = json.load(file)
    return data


def load_settings(environment: str):
    settings_data = getsettings("chatbot2_settings.json")
    env_settings = settings_data[environment]

    if environment == "testbench":
        users = settings_data["debug_users"]
    else:
        users = settings_data["users"]

    return Settings(
        environment=environment,
        logging_path=env_settings["logging_path"],
        users=users,
        slackapi_key=os.environ.get(env_settings["slackapi_key_env_var"]),
        openai_key=os.environ.get("OPENAI_KEY"),
        mindset=env_settings["mindset"]
    )


CONTEXT = {}
logging.basicConfig(filename="chatbot_messages.log", level=logging.INFO)


# ---------------------------------------------


def replacenames(message_text_, userlist):
    """Replace Slack ID with Name"""
    for user, name in userlist.items():
        replacetarget = f"<@{user}>"
        message_text_ = message_text_.replace(replacetarget, name["name"])
    print(message_text_)
    return message_text_


def allowed_user(user_list, user):
    """Determine if a user has access"""
    try:
        return user_list[user]["active"]
    except KeyError:
        return False


def log_message(thread, user, msg):
    if msg is not None:
        log_entry = f"[{datetime.now()}]:[{user}]:[{thread}]:[{msg}]"
        print(log_entry)
        logging.info(log_entry)


async def respond_message(event_, environment="prod"):
    """
    Respond to the user's message
    """
    settings = load_settings(environment)
    client = AsyncWebClient(token=settings.slackapi_key)
    openai_client = openai.AsyncOpenAI(api_key=settings.openai_key, timeout=60.0)
    

    if (event_.get('text')) is not None:
        channel_id = event_.get('channel')  # Channel where the mention occurred
        thread_id = event_.get('thread_ts') or event_.get('ts')  # Respond if in thread
        user_id = event_.get('user')  # ID of the user

        # Ignore bot messages
        if settings.users[user_id]["bot"] or (event_.get('text')) is None:
            return None
        
        # Reject if the user isn't allowed access
        if not allowed_user(settings.users, user_id):
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_id,
                text="""Sorry, looks like you don't have access. 
                Ensure your KnowBe4 training has been completed and then reach out to Kevan to gain access."""
            )
            return None
        
        # Text of the message where the bot was mentioned
        for bot_id in settings.users:
            if settings.users[bot_id]["bot"]:
                message_text = (event_.get('text')).replace(f"@<{bot_id}>", "")    
        sender = settings.users[user_id]["name"]
        message_text = f"{sender} asks: {message_text}"

        # Check if conversation already exists
        if thread_id not in CONTEXT:
            ini_mind = {"role": "system", "content": settings.mindset}
            CONTEXT[thread_id] = [ini_mind]

        CONTEXT[thread_id].append({
            "role": "user",
            "content": replacenames(message_text, settings.users)
        })

        try:
            # Respond to the user immediately
            initial_response = await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_id,
                text="[Generating message... :loading-blue:]"
            )
            initial_ts = initial_response['ts']

            # Generate response to the query
            stream = await openai_client.chat.completions.create(
                model="gpt-4o-2024-05-13",
                messages=CONTEXT[thread_id],
                stream=True,
            )

            message_ = ""
            message_size = 250

            async for part in stream:
                message_piece = (part.choices[0].delta.content or "")
                message_ += message_piece
                
                # Post small chunks - at a time
                if len(message_) > message_size:
                    message_size += 250
                    await client.chat_update(
                        channel=event_['channel'],
                        text=message_ + "\n[Generating message... :loading-blue:]",
                        thread_ts=thread_id,
                        ts=initial_ts
                    )

        except openai.BadRequestError:
            message_ = """This model's maximum context length is 4097 tokens per conversation thread. 
            However, your messages have exceeded this limit. 
            You can work around this by creating a new Slack thread with a summarized context of this conversation."""
        
        except Exception as e:
            message_ += f"An error occurred during text generation: {str(e)}"
        
        finally:
            # Update message with full response
            await client.chat_update(
                channel=event_['channel'],
                text=message_ + "\n---",
                thread_ts=thread_id,
                ts=initial_ts
            )

            log_message(thread_id, "assistant", message_)
            CONTEXT[thread_id].append({
                "role": "assistant",
                "content": message_
            })
            
            return message_

# ---------------------------------------------


class EventRequest(BaseModel):
    token: str
    team_id: str = Field(None, alias='team_id')
    api_app_id: str = Field(None, alias='api_app_id')
    event: dict = Field(None, alias='event')
    type: str
    challenge: str = Field(None, alias='challenge')
    event_id: str = Field(None, alias='event_id')
    event_time: int = Field(None, alias='event_time')


async def receive_slack(request, event_request, environment):
    # For Slack URL verification
    if event_request.type == 'url_verification' and event_request.challenge:
        return {"challenge": event_request.challenge}

    # X-Slack-Retry-Num avoid duplicate events - Acknowledge without resending
    if request.headers.get('X-Slack-Retry-Num'):
        return {"status": "acknowledged"}

    # Listen for Slack Events
    if event_request.type == 'event_callback' and event_request.event:
        event = event_request.event
        # Handle the event when the bot is mentioned or messaged
        if event.get('type') == 'app_mention' or (event.get('type') == 'message' and event.get('channel_type') == 'im'):
            try:
                log_message(event.get('thread_ts') or event.get('ts'), event.get('user'), event.get('text'))
                await respond_message(event, environment)
            except SlackApiError as e:
                raise HTTPException(status_code=500, detail=f"Error posting message: {e}") from e

# ---------------------------------------------

@app.post("/")
async def slack_events(request: Request, event_request: EventRequest):
    """
    ChatBot - Default
    """
    
    await receive_slack(request, event_request, environment="prod")
    return {"status": "OK"}

@app.post("/mamaru")
async def slack_events_ru(request: Request, event_request: EventRequest):
    """
    ChatBot - MamaRu
    """

    await receive_slack(request, event_request, environment="mamaru")
    return {"status": "OK"}

@app.post("/testbench")
async def slack_events_debug(request: Request, event_request: EventRequest):
    """
    ChatBot - Testbench
    """
    
    await receive_slack(request, event_request, environment="testbench")
    return {"status": "OK"}

# ---------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

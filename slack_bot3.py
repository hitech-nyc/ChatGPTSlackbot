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

DEBUG = False
CONTEXT = {}
app = FastAPI()

def getsettings(filename):
    """
    Load settings from JSON
    """
    with open(filename, 'r') as file:
        data = json.load(file)
    return data
# Load settings from 'chatbot_settings.json'
settings = getsettings("chatbot_settings.json")

# Configure settings based on DEBUG mode
if DEBUG:
    # Debug mode settings
    bot_id = settings["debug"]["bot_id"]
    logging.basicConfig(filename=settings["debug"]["logging_path"], level=logging.INFO)
    USERLIST = settings["debug"]["users"]
    slackapi_key = os.environ.get("SLACKAPI_KEY_DEBUG")
    openapi_key = os.environ.get("OPENAI_KEY")
else:
    # Production mode settings
    bot_id = settings["prod"]["bot_id"]
    logging.basicConfig(filename=settings["prod"]["logging_path"], level=logging.INFO)
    USERLIST = settings["prod"]["users"]
    slackapi_key = os.environ.get("SLACKAPI_KEY")
    openapi_key = os.environ.get("OPENAI_KEY")

# Initialize Slack and OpenAI clients
client = AsyncWebClient(token=slackapi_key)
openai_client = openai.AsyncOpenAI(api_key=openapi_key,timeout=60.0)

# ---------------------------------------------

def replacenames(string,userlist):
    """
    Replace Slack ID with user's name
    """

    for user,attributes in userlist.items():
        string = string.replace(user,attributes["name"])

    return string

def allowed_user(user):
    """
    Determine if a user has access
    """

    try:
        return USERLIST[user]
    except KeyError:
        return False


def log_message(thread,user,msg):
    """
    Format for generated logs
    """

    if msg is not None:
        log_entry = (f"[{datetime.now()}]:[{user}]:[{thread}]:[{msg}]")
        print(f"[{datetime.now()}]:[{user}]:[{thread}]:[{msg[0:50]}]")
        logging.info(log_entry)


async def respond_message(event_):
    """
    Respond to the user's message
    """

    # Extract message and user details from the event
    if (event_.get('text')) is not None:
        # Channel where the mention occurred
        channel_id = event_.get('channel')
         # Text of the message where the bot was mentioned
        message_text = (event_.get('text')).replace(f"@<{bot_id}>","")
        # Respond if in thread
        thread_id = event_.get('thread_ts') or event_.get('ts')
        # ID of the user who mentioned the bot
        user_id = event_.get('user')

        # Ignore bot messages
        if user_id == bot_id or message_text is None:
            return None
        
        # Reject if the user isn't allowed access
        if allowed_user(user_id) is False:
            initial_response = await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_id, 
                text="""Sorry looks like you don't have access.
                Ensure your KnowBe4 training has been completed and then reach out to Kevan to gain access.""")
            return None  

        # Check if conversation already exists
        try:
            CONTEXT[thread_id].append({
                "role":"user",
                "content":replacenames(message_text,USERLIST)
                })
        except KeyError:
            CONTEXT[thread_id] = [
                {"role":"user",
                    "content":replacenames(message_text,USERLIST)
                    }]
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
                model = "gpt-3.5-turbo",
                messages = CONTEXT[thread_id],
                stream = True,
            )
            
            message_ = ""
            message_size = 250
            async for part in stream:
                message_piece = (part.choices[0].delta.content or "")
                message_ += message_piece      
                # Post small chunks - at a time
                if len(message_) > message_size:
                    #print(message_[message_size-150:message_size])
                    message_size += 250

                    await client.chat_update(
                        channel=event_['channel'],
                        text=message_+"\n[Generating message... :loading-blue:]",
                        thread_ts=thread_id,
                        ts=initial_ts)
        
        except openai.BadRequestError:
            # Token length error
            message_ = """This model's maximum context length is 4097 tokens. 
            However, your messages have exceeded this limit. 
            You can work around this by creating a new thread with a summarized context of this conversation."""
        finally:
            # Update message with full response
            await client.chat_update(
            channel=event_['channel'],
            text=message_+"\n---",
            thread_ts=thread_id,
            ts=initial_ts)       

            log_message(thread_id,"assistant",message_)
            CONTEXT[thread_id].append({"role":"assistant","content":message_})
            return message_
 

# ---------------------------------------------
# -------------------

class EventRequest(BaseModel):
    """
    Define the request model
    """
    token: str
    team_id: str = Field(None, alias='team_id')
    api_app_id: str = Field(None, alias='api_app_id')
    event: dict = Field(None, alias='event')
    type: str
    challenge: str = Field(None, alias='challenge')
    event_id: str = Field(None, alias='event_id')
    event_time: int = Field(None, alias='event_time')

@app.post("/")
async def slack_events(request: Request, event_request: EventRequest):
    """
    Receive Slack URL event
    """
    # For Slack URL verification
    if event_request.type == 'url_verification' and event_request.challenge:
        return  {"challenge": event_request.challenge}

    # X-Slack-Retry-Num avoid duplicate events - Acknowledge without resending
    if request.headers.get('X-Slack-Retry-Num'):
        return {"status": "acknowledged"}

    # Listen for Slack Events
    if event_request.type == 'event_callback' and event_request.event:
        event = event_request.event
        # Handle the event when the bot is mentioned or messaged
        if event.get('type') == 'app_mention' or (event.get('type') == 'message' and event.get('channel_type') == 'im'):
            try:
                log_message(event.get('thread_ts') or event.get('ts'),event.get('user'),event.get('text'))
                await respond_message(event)
            except SlackApiError as e:
                raise HTTPException(status_code=500, detail=f"Error posting message: {e}") from e

    return {"status": "OK"}

# ---------------------------------------------


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)

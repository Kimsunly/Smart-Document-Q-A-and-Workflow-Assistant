from slack_bolt import App
from slack_sdk.errors import SlackApiError
from automation.config import SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET
from automation.tasks import ingest_and_index_file

app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)

@app.event("file_shared")
def handle_file_shared(event, client, logger):
    try:
        file_id = event.get("file_id") or event.get("file", {}).get("id")
        if not file_id:
            return
        info = client.files_info(file=file_id)
        url = info["file"]["url_private_download"]
        # download via bot token
        resp = client.api_call("files.download", params={"file": file_id})
        # resp is a binary body in Bolt adapter; for clarity use web client
        # Simplest approach: use requests with auth
        import requests
        headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            ingest_and_index_file.delay(r.content, info["file"]["name"], "slack")
    except SlackApiError as e:
        logger.error("slack file error: %s", e)

@app.command("/list_docs")
def cmd_list_docs(ack, respond):
    ack()
    respond("Listing documents is not implemented yet. Use /help.")
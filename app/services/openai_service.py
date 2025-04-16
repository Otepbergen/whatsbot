from openai import OpenAI
import shelve
from dotenv import load_dotenv
import os
import time
import logging
import openai

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
client = OpenAI(api_key=OPENAI_API_KEY)


# --------------------------------------------------------------
# Upload file
# --------------------------------------------------------------
def upload_file(path):
    # Загружаем файл с целью использования в ассистенте
    file = client.files.create(file=open(path, "rb"), purpose="assistants")
    return file

# Путь к файлу
file_path = "C:\\whabot\\python-whatsapp-bot\\data\\airbnb-faq.pdf"
uploaded_file = upload_file(file_path)

# --------------------------------------------------------------
# Create vector store and attach file
# --------------------------------------------------------------
def create_vector_store(file_path):
    vector_store = client.vector_stores.create(name="Airbnb FAQ Vector Store")
    
    # Загружаем и индексируем файл в векторное хранилище
    client.vector_stores.file_batches.upload_and_poll(
        vector_store_id=vector_store.id,
        files=[open(file_path, "rb")]
    )
    return vector_store

vector_store = create_vector_store(file_path)

# --------------------------------------------------------------
# Create assistant and connect vector store
# --------------------------------------------------------------
def create_assistant(vector_store_id):
    assistant = client.beta.assistants.create(
        name="WhatsApp AirBnb Assistant",
        instructions="You're a helpful WhatsApp assistant that can assist guests that are staying in our Paris AirBnb. Use your knowledge base to best respond to customer queries. If you don't know the answer, say simply that you cannot help with the question and advise to contact the host directly. Be friendly and funny.",
        tools=[{"type": "file_search"}],
        model="gpt-4o",
        tool_resources={
            "file_search": {
                "vector_store_ids": [vector_store_id]
            }
        }
    )
    return assistant

assistant = create_assistant(vector_store.id)

print("Ассистент успешно создан! ID:", assistant.id)


# Use context manager to ensure the shelf file is closed properly
def check_if_thread_exists(wa_id):
    with shelve.open("threads_db") as threads_shelf:
        return threads_shelf.get(wa_id, None)


def store_thread(wa_id, thread_id):
    with shelve.open("threads_db", writeback=True) as threads_shelf:
        threads_shelf[wa_id] = thread_id


def run_assistant(thread, name):
    # Retrieve the Assistant
    assistant = client.beta.assistants.retrieve(OPENAI_ASSISTANT_ID)

    # Run the assistant
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id,
        # instructions=f"You are having a conversation with {name}",
    )

    # Wait for completion
    # https://platform.openai.com/docs/assistants/how-it-works/runs-and-run-steps#:~:text=under%20failed_at.-,Polling%20for%20updates,-In%20order%20to
    while run.status != "completed":
        # Be nice to the API
        time.sleep(0.5)
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

    # Retrieve the Messages
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    new_message = messages.data[0].content[0].text.value
    logging.info(f"Generated message: {new_message}")
    return new_message

def generate_response(message_body, wa_id, name):
    # Check if there is already a thread_id for the wa_id
    thread_id = check_if_thread_exists(wa_id)

    # Try to retrieve existing thread
    thread = None
    if thread_id:
        try:
            logging.info(f"Retrieving existing thread for {name} with wa_id {wa_id}")
            thread = client.beta.threads.retrieve(thread_id)
        except openai.NotFoundError:
            logging.warning(f"Thread {thread_id} not found. Creating a new one.")
            thread = client.beta.threads.create()
            store_thread(wa_id, thread.id)  # Сохраняем новый thread_id
    else:
        logging.info(f"Creating new thread for {name} with wa_id {wa_id}")
        thread = client.beta.threads.create()
        store_thread(wa_id, thread.id)

    # Add message to thread
    message = client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=message_body,
    )

    # Run the assistant and get the new message
    new_message = run_assistant(thread, name)

    return new_message


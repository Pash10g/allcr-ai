import streamlit as st
from pymongo import MongoClient
from PIL import Image
import io
import os
import base64
import openai
import json
from haystack.dataclasses import ChatMessage
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack import Pipeline
from haystack.utils import Secret

# OpenAI API key
openai.api_key = os.environ.get("OPENAI_API_KEY")

API_CODE = os.environ.get("API_CODE")

# Initialize session state for authentication
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

def auth_form():
    st.title("Authentication")
    st.write("Please enter the API code to access the application.")
    api_code = st.text_input("API Code", type="password")
    if st.button("Submit"):
        if api_code == API_CODE:
            st.session_state.authenticated = True
            st.success("Authentication successful.")
            st.rerun()  # Re-run the script to remove the auth form
        else:
            st.error("Authentication failed. Please try again.")

# MongoDB connection
client = MongoClient(os.environ.get("MONGODB_ATLAS_URI"))
db = client['ocr_db']
collection = db['ocr_documents']

transcribed_object = "other"

# Function to transform image to text using OpenAI
def transform_image_to_text(image):
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='JPEG')
    img_byte_arr = img_byte_arr.getvalue()
    encoded_image = base64.b64encode(img_byte_arr).decode('utf-8')

    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{
        "role": "system",
        "content": "You are an ocr to json expert looking to transcribe an image. If the type is 'other' please specify the type of object and clasiffy as you see fit."
        },
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": f"Please trunscribe this {transcribed_object} into a json only output for MongoDB store. Always have a 'name' and 'type' top field (type is a subdocument with user and 'ai_classified') as well as other fields as you see fit."
        },
        {
          "type": "image_url",
          "image_url": {
            "url": f"data:image/jpeg;base64,{encoded_image}"
          }
        }
      ]
    }
  ]
    )
    extracted_text = response.choices[0].message.content
    return extracted_text

# Function to save image and text to MongoDB
def save_image_to_mongodb(image, description):
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='JPEG')
    img_byte_arr = img_byte_arr.getvalue()
    encoded_image = base64.b64encode(img_byte_arr).decode('utf-8')
    
    # Remove the ```json and ``` parts
    cleaned_document = description.strip().strip("```json").strip("```").strip()

    # Parse the cleaned JSON string into a Python dictionary
    document = json.loads(cleaned_document)
    collection.insert_one({
        'image': encoded_image,
        'ocr': document
    })

# Function to search and display images from MongoDB using Haystack
def search_and_display_images(query):
    prompt_builder = DynamicChatPromptBuilder()
    llm = OpenAIChatGenerator(api_key=Secret.from_token("your_openai_api_key"), model="gpt-3.5-turbo")

    pipe = Pipeline()
    pipe.add_component("prompt_builder", prompt_builder)
    pipe.add_component("llm", llm)
    pipe.connect("prompt_builder.prompt", "llm.messages")

    messages = [ChatMessage.from_system("Always respond in German even if some input data is in other languages."),
                ChatMessage.from_user(f"Search for recipes containing: {query}")]

    results = collection.find({"description": {"$regex": query, "$options": "i"}})
    for result in results:
        st.write(result['description'])
        image_data = base64.b64decode(result['image'])
        image = Image.open(io.BytesIO(image_data))
        st.image(image, use_column_width=True)

# Main app logic
if not st.session_state.authenticated:
    auth_form()
else:
    st.title("👀 AllCR App")

    # Image capture
    st.header("Capture Objects with AI")
    st.divider()
    st.write("Capture real life objects like Recipes, Documents, Animals, Vehicles, etc., and turn them into searchable documents.")
    options = st.multiselect(
        "What do you want to capture?",
        ["Recipe", "Document", "Animal", "Vehicle", "Product", "Other"], ["Other"])

    transcribed_object = options[0] if options else "other"
    image = st.camera_input("Take a picture")

    if st.button("Save to MongoDB"):
        if image is not None:
            img = Image.open(io.BytesIO(image.getvalue()))
            extracted_text = transform_image_to_text(img)
            st.write("Processed Document")
            st.write(extracted_text)
            if st.button("Confirm Save to MongoDB"):
                save_image_to_mongodb(img, extracted_text)
                st.experimental_rerun()

    st.header("Recorded Documents")
    docs = list(collection.find())

    for doc in docs:
        expander = st.expander(f"{doc['ocr']['type']} '{doc['ocr']['name']}'")
        expander.write(doc['ocr'])
        if expander.button("Show Image", key=str(doc['_id'])):
            image_data = base64.b64decode(doc['image'])
            image = Image.open(io.BytesIO(image_data))
            expander.image(image, use_column_width=True)

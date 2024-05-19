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
# MongoDB connection
client = MongoClient(os.environ.get("MONGODB_ATLAS_URI"))
db = client['ocr_db']
collection = db['ocr_documents']


auth_collection=db['api_keys']
# Initialize session state for authentication
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

def auth_form():
    
    st.title("Authentication")
    st.write("Please enter the API code to access the application.")
    api_code = st.text_input("API Code", type="password")
    if st.button("Submit"):
        st.toast("Authenticating...", icon="⚠️")
        db_api_key=auth_collection.find_one({"api_key":api_code})
        if db_api_key:
            st.session_state.authenticated = True
            st.session_state.api_code = api_code
            st.success("Authentication successful.")
            st.rerun()  # Re-run the script to remove the auth form
        else:
            st.error("Authentication failed. Please try again.")



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

    response = openai.embeddings.create(
    input=json.dumps({
        'name' : document['name'],
        'type' : document['type']
    }),
    model="text-embedding-3-small"
)

    gen_embeddings=response.data[0].embedding

    collection.insert_one({
        'image': encoded_image,
        'api_key': st.session_state.api_code,
        'embedding' : gen_embeddings,
        'ocr': document
    })

def search_aggregation(search_query):
    docs = list(collection.aggregate([
        {
            '$search': {
                'index': 'search', 
                'compound': {
                    'should': [
                        {
                            'text': {
                                'query': search_query, 
                                'path': {
                                    'wildcard': '*'
                                }, 
                                'fuzzy': {
                                    'maxEdits' : 2
                                }
                            }
                        }
                    ], 
                    'filter': [
                        {
                            'queryString': {
                                'defaultPath': 'api_key', 
                                'query': st.session_state.api_code
                            }
                        }
                    ]
                }
            }
        }
    ]))
    return docs   

def vector_search_aggregation(search_query):
    query_resp = openai.embeddings.create(
        input=search_query,
        model="text-embedding-3-small"
    )
    query_vec = query_resp.data[0].embedding
    docs = list(collection.aggregate([
        {
            '$vectorSearch': {
                'index': 'vector_index', 
                'queryVector': query_vec, 
                'path': 'embedding', 
                'numCandidates' : 20,
                'limit' : 1,
                'filter': {
                    'api_key': st.session_state.api_code
                }
            }}
    ]))
    return docs

# Main app logic
if not st.session_state.authenticated:
    auth_form()
else:
    st.toast("Authenticated", icon="👍")
    st.title("👀 AllCR App")

    # Image capture
    st.header("Capture Objects with AI")
    st.divider()
    st.write("Capture real life objects like Recipes, Documents, Animals, Vehicles, etc., and turn them into searchable documents.")
    options = st.multiselect(
        "What do you want to capture?",
        ["Recipe", "Document", "Animal", "Vehicle", "Product", "Sports", "Other"], ["Other"])

    transcribed_object = options[0] if options else "other"
    image = st.camera_input("Take a picture")

    @st.experimental_dialog("Processed Document",width="large")
    def show_dialog():
        st.write(extracted_text)
        if st.button("Confirm Save to MongoDB"):
            

        
            save_image_to_mongodb(img, extracted_text)
            st.rerun()
            
            


    if st.button("Analyze image for MongoDB"):
        if image is not None:
            img = Image.open(io.BytesIO(image.getvalue()))
            extracted_text = transform_image_to_text(img)
            show_dialog()
            

    # Search functionality
    st.header("Recorded Documents")
    
    

    ## Adding search bar
    search_query = st.text_input("Search for documents")
    toggle_vector_search = st.toggle("Vector Search", False)
    if search_query:
        if not toggle_vector_search:
            docs = search_aggregation(search_query)
        else:
            docs = vector_search_aggregation(search_query)
    else:
        docs = list(collection.find({"api_key": st.session_state.api_code}))
    for doc in docs:
        expander = st.expander(f"{doc['ocr']['type']} '{doc['ocr']['name']}'")
        expander.write(doc['ocr'])  # Ensure 'recipe' matches your MongoDB field name
        ## collapseble image
        
        if expander.button("Show Image", key=doc['_id']):
            image_data = base64.b64decode(doc['image'])
            image = Image.open(io.BytesIO(image_data))
            expander.image(image, use_column_width=True)

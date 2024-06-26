import streamlit as st
from pymongo import MongoClient
from bson.objectid import ObjectId
from PIL import Image
import io
import os
import base64
import openai
import json
from audio_recorder_streamlit import audio_recorder
import filetype
import tempfile

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

if 'messages' not in st.session_state:
    st.session_state.messages = []


def auth_form():
    

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
def transform_image_to_text(image, format):
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format=format)
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
          "text": f"Please trunscribe this {transcribed_object} into a json only output for MongoDB store, calture all data as a single document. Always have a 'name', 'summary' (for embedding ) and 'type' top field (type is a subdocument with user and 'ai_classified') as well as other fields as you see fit."
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

def clean_document(document):
    cleaned_document = document.strip().strip("```json").strip("```").strip()
    return json.loads(cleaned_document)

# Function to save image and text to MongoDB
def save_image_to_mongodb(image, description):
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format=image.format)
    img_byte_arr = img_byte_arr.getvalue()
    encoded_image = base64.b64encode(img_byte_arr).decode('utf-8')
    
    # Remove the ```json and ``` parts
    

    # Parse the cleaned JSON string into a Python dictionary
    document = clean_document(description)

    response = openai.embeddings.create(
    input=json.dumps({
        'name' : document['name'],
        'summary' : document['summary']
    }),
    model="text-embedding-3-small"
)

    gen_embeddings=response.data[0].embedding

    collection.insert_one({
        'image': encoded_image,
        'api_key': st.session_state.api_code,
        'embedding' : gen_embeddings,
        'ocr': document,
        'ai_tasks': []
    })

def get_ai_task(ocr,prompt):
    ## Use existing document as context and perform another GPT task
    ocr_text = json.dumps(ocr)
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{
        "role": "system",
        "content": "You are  a task assistant looking to create a task for the AI to perform on the JSON object. Please return plain output which is only copy paste with no explanation."
        },
        {
        "role": "user",
        "content": f"Please perform the following task {prompt}  on the following JSON object {ocr_text}. Make sure that the output is stright forward to copy paste."
        }
        ]
        )
    
    return response.choices[0].message.content

def save_ai_task(task_id, task_result, prompt):

    collection.update_one(
        {"_id": ObjectId(task_id)},
        {"$push" : {"ai_tasks" : {'prompt' : prompt, 'result' : task_result}}}
    )

    return "Task saved successfully."

def ai_chat(query,message):
    relevant_docs = vector_search_aggregation(query, 3)
    context = ''
    for doc in relevant_docs:
        context+=json.dumps(doc['ocr'])
    messages=[{"role": "system", "content": "You are an assistant that uses document context to answer questions. Answer not too long and concise answers."}]
    for chat_message in st.session_state.messages:
        messages.append(chat_message)

    messages.append({"role": "user", "content": f"Using the following context, please answer the question: {query}\n\nContext:\n{context}"})
        
    stream = openai.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        stream=True
    )
    response = message.write_stream(stream)

    st.session_state.messages.append({"role": "assistant", "content": response})
    
def transcribe_audio_and_store(audio_path):
    audio_file= open(audio_path, "rb")
    response = openai.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file
    )

    transcript = response.text
    document = {
        'api_key': st.session_state.api_code,
        'ocr' :{
            'name' : f"Audio Transcribe of {transcript[:15]}...",
            'summary': transcript,
            'transcription': {'text' : transcript },
            'type': 'audio_transcription'
        },
        'ai_tasks': []
    }    

    # Save to MongoDB with embeddings
    response = openai.embeddings.create(
    input=json.dumps({
        'name' : document['ocr']['name'],
        'summary' : document['ocr']['summary']
    }),
    model="text-embedding-3-small"
)

    gen_embeddings=response.data[0].embedding

    document['embedding'] = gen_embeddings

    collection.insert_one(document)

    st.rerun()
    

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

def vector_search_aggregation(search_query, limit):
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
                'limit' : limit,
                'filter': {
                    'api_key': st.session_state.api_code
                }
            }},
            { '$project' : {'embedding'  : 0} }
    ]))
    return docs

def show_previous_tasks(work_doc,st):
    if 'ai_tasks' in work_doc and len(work_doc['ai_tasks']) > 0:
        st.markdown("### Previous Tasks")
        for task in work_doc['ai_tasks']:
            with st.expander(f"Task: {task['prompt']}"):
                text, markdown = st.tabs(["text", "markdown"])
                with text:
                    st.markdown(task['result'])
                with markdown:
                    st.code(task['result'])
    else:
        st.write("No previous tasks found.")

# Main app logic
if not st.session_state.authenticated:
    auth_form()
else:
    st.title("👂👀👂 AllCR App")

    

    # Image capture
    st.header("Capture Objects with AI")
    st.divider()
    st.write("Capture or listen to real life objects like Recipes, Documents, Animals, Vehicles, etc., and turn them into searchable documents.")
    options = st.multiselect(
        "What do you want to capture?",
        ["Recipe", "Diagram", "Post", "Screenshot","Document", "Animal", "Vehicle", "Product", "Sports", "Other"], ["Other"])

    transcribed_object = options[0] if options else "other"
    tab_cam, tab_upl, tab_rec = st.tabs(["Camera", "Upload", "Record"])
    is_audio=False
    with tab_cam:
        is_audio=False
        image = st.camera_input("Take a picture")

    with tab_upl:
        is_audio=False
        uploaded_file = st.file_uploader("Choose a file")
        if uploaded_file is not None:
        # To read file as bytes:
            image = uploaded_file

    with tab_rec:
        st.write("Record and Transcribe Audio")
        is_audio=True
        audio_bytes = audio_recorder(energy_threshold=-1.0)
        if audio_bytes:
            kind = filetype.guess(audio_bytes)
            if kind is None:
                st.warning("Cannot determine the audio format.")
            else:
                st.success(f"The recorded audio format is {kind.mime}.")
               
            audio_file = st.audio(audio_bytes, format="audio/wav")
 
            if st.button("Transcribe"):
                if audio_file:
                    # save as wav file
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as fp:
                        fp.write(audio_bytes)
                        audio_bytes = fp.name
                    with st.spinner("Transcribing audio and storing..."):
                        transcribe_audio_and_store(audio_bytes)

    @st.experimental_dialog("Processed Document",width="large")
    def show_dialog():
        st.write(extracted_text)
        if st.button("Confirm Save to MongoDB"):
        
            save_image_to_mongodb(img, extracted_text)
            st.rerun()
            
    @st.experimental_dialog("AI Task on Document",width="large")
    def show_prompt_dialog(work_doc):
        st.header("Please describe the AI processing to be done on the document.")
        st.markdown(f"""### Document: {work_doc['ocr']['name']} 
                                 
                                 Example: Translate this document to French.
                                 """)
        prompt = st.text_area("AI Prompt")
        if st.button("Confirm task"):
            result = get_ai_task(work_doc['ocr'],prompt)
            st.code(result)
            res = save_ai_task(work_doc['_id'], result, prompt)
            st.success(res)
            work_doc['ai_tasks'].append({'prompt' : prompt,
                                        'result' : result})
            # if st.button("Save Task to Document"):
        ## if length of array bigger than 0
        show_previous_tasks(work_doc, st)
        # if 'ai_tasks' in work_doc and len(work_doc['ai_tasks']) > 0:
        #     st.markdown("### Previous Tasks")
        #     for task in work_doc['ai_tasks']:
        #         with st.expander(f"Task: {task['prompt']}"):
        #             text, markdown = st.tabs(["text", "markdown"])
        #             with text:
        #                 st.markdown(task['result'])
        #             with markdown:
        #                 st.code(task['result'])
        # else:
        #     st.write("No previous tasks found.")
                
                
                 

    if st.button("Analyze image for MongoDB"):
        if image is not None:
            with st.spinner("Analysing document with GPT..."):
                img = Image.open(io.BytesIO(image.getvalue()))
                extracted_text = transform_image_to_text(img, img.format)
            show_dialog()
        

    # Search functionality
    with st.sidebar:
        st.header("Chat with AI")

        if st.button("New Chat"):
            st.session_state.messages=[]
       
        messages = st.container(height=500)
        for message in st.session_state.messages:
            with messages.chat_message(message["role"]):
                messages.markdown(message["content"])

        # Accept user input
        if prompt := st.chat_input("Ask me something about the docs..."):
            # Add user message to chat history
            st.session_state.messages.append({"role": "user", "content": prompt})
            # Display user message in chat message container
            with messages.chat_message("user"):
                messages.markdown(prompt)
            with st.spinner('RAGing...'):
                
                with messages.chat_message("assistant"):
                    response = ai_chat(prompt, st)
    

    ## Adding search bar
    search_query = st.text_input("Search for documents")
    toggle_vector_search = st.toggle("Vector Search", False)
    if search_query:
        if not toggle_vector_search:
            docs = search_aggregation(search_query)
        else:
            docs = vector_search_aggregation(search_query, 5)
    else:
        docs = list(collection.find({"api_key": st.session_state.api_code}).sort({"_id": -1}))
    for doc in docs:
        expander = st.expander(f"{doc['ocr']['type']} '{doc['ocr']['name']}'")
        expander.write(doc['ocr'])  # Ensure 'recipe' matches your MongoDB field name
        ## collapseble image

        image_col, prompt_col = expander.columns(2)
        
        with image_col:
            if 'image' in doc:
                if expander.button("Show Image", key=f"{doc['_id']}-image"):
                    image_data = base64.b64decode(doc['image'])
                    image = Image.open(io.BytesIO(image_data))
                    expander.image(image, use_column_width=True)

        with prompt_col:
            if expander.button("Run AI Prompt", key=f"{doc['_id']}-prompt"):
               show_prompt_dialog(doc)

        

   

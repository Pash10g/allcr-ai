# 👀 AllCR App

AllCR App is a Streamlit application that allows users to capture real-life objects like recipes, documents, animals, vehicles, and more, and turn them into searchable documents. The app integrates with OpenAI's GPT-4 for OCR (Optical Character Recognition) to JSON conversion and MongoDB Atlas for storing the extracted information.

## Features

- **Authentication**: Secure access to the application using an API code.
- **Image Capture**: Capture images using your device's camera.
- **OCR to JSON**: Convert captured images to JSON format using OpenAI's GPT-4.
- **MongoDB Integration**: Store and retrieve the extracted information from MongoDB.
- **Search and Display**: Search and display stored documents along with their images.

## Requirements

- Python 3.8+
- Streamlit
- OpenAI Python Client Library
- MongoDB Atlas cluster
- PIL (Python Imaging Library)
- Haystack (for advanced search functionality)

## Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/yourusername/allcr-app.git
   cd allcr-app

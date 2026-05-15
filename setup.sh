#!/bin/bash

# Nalaris Bookkeeper - Ubuntu Environment Setup Script
# This script installs system dependencies, Python, and all required libraries.

echo "🚀 Starting Nalaris environment setup..."

# 1. Update System Packages
sudo apt update && sudo apt upgrade -y

# 2. Install Python, Pip, and Virtual Environment tools
echo "📦 Installing Python and essential build tools..."
sudo apt install -y python3 python3-pip python3-venv build-essential

# 3. Install System Libraries for Image Processing
# libheif is required for pillow-heif to handle iPhone .HEIC photos
echo "🖼️ Installing image processing dependencies..."
sudo apt install -y libheif-dev libde265-dev libjpeg-dev zlib1g-dev

# 4. Create and Activate Virtual Environment (Best Practice)
echo "🌐 Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 5. Install Python Dependencies
echo "🐍 Installing Python libraries..."
pip install --upgrade pip
pip install fastapi uvicorn python-multipart python-dotenv google-genai Pillow pillow-heif

# 6. Final verification
echo "------------------------------------------------"
echo "✅ Setup Complete!"
echo "------------------------------------------------"
echo "Next steps:"
echo "1. Ensure your .env file is present with your GEMINI_API_KEY."
echo "2. Activate your environment: source venv/bin/activate"
echo "3. Run the server: python3 server.py"
echo "------------------------------------------------"
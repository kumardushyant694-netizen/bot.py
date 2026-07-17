#!/bin/bash

echo "🚀 Starting DARk Aadhar Bot..."

if [ ! -f "user_credits.json" ]; then
    echo "{}" > user_credits.json
    echo "✅ Created user_credits.json"
fi

pip install -r requirements.txt

echo "✅ Bot started!"
python adhar.py

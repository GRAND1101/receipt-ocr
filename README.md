## Receipt OCR Web App (Graduation Project)

This project is my **Graduation Project**, aiming to build a web-based platform that can automatically extract and analyze expense data from store receipts.  
The core engine relies on **[Tesseract OCR](https://github.com/tesseract-ocr/tesseract)**, an open-source Optical Character Recognition library, combined with custom parsing and classification logic.  

By leveraging open-source technology, the project demonstrates how everyday financial tasks—such as managing receipts and tracking monthly budgets—can be automated into a user-friendly web application.

### ✨ Features
- **OCR powered by Tesseract (kor+eng)**: extract text from scanned or photographed receipts.
- Automatic parsing of:
  - Store name
  - Transaction date/time
  - Total amount
  - Category (with learning support for store names)
- Monthly expense statistics with filtering.
- Lightweight **SQLite** database for storing parsed results.
- Deployed on **Render (Docker)** as a web service.

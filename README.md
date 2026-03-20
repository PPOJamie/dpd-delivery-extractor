# DPD Delivery Note Extractor

A Streamlit web app for uploading multiple delivery note PDFs and exporting a single CSV.

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Community Cloud

1. Put `app.py` and `requirements.txt` in a GitHub repository.
2. Sign in to Streamlit Community Cloud with GitHub.
3. Create a new app and select the repository plus `app.py` as the entrypoint.
4. Deploy and share the generated `*.streamlit.app` link.


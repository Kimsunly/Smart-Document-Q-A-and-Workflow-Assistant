import streamlit as st

st.title("Smart Document Q&A Assistant")
st.write("🚀 Streamlit is working!")

uploaded_file = st.file_uploader("Upload a PDF", type="pdf")

if uploaded_file is not None:
    st.success(f"Uploaded: {uploaded_file.name}")

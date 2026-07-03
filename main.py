from fastapi import FastAPI
from routers import auth

# We will import our routers here as we build them
# from routers import auth, braille, history, admin

app = FastAPI(title="InfoX Assistive Reader API")

# Example of how we will wire up the routes later:
app.include_router(auth.router, tags=["Authentication"])

@app.get("/")
def health_check():
    """A simple endpoint to verify the server is running."""
    return {"status": "InfoX API is online and modular!"}
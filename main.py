from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# We will import our routers here as we build them
from routers import auth, settings, admin
# from routers import braille, history

app = FastAPI(title="InfoX Assistive Reader API")

# CORS middleware — allow the admin panel (Vercel) and local dev to access the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",       # Next.js local dev
        "https://infox-admin-alpha.vercel.app/",
        # Add your Vercel deployment URL here once deployed, e.g.:
        # "https://infox-admin.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Example of how we will wire up the routes later:
app.include_router(auth.router, tags=["Authentication"])
app.include_router(settings.router, prefix="/settings", tags=["Settings"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])

@app.get("/")
def health_check():
    """A simple endpoint to verify the server is running."""
    return {"status": "InfoX API is online and modular!"}
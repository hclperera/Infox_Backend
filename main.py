from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# We will import our routers here as we build them
from routers import auth, settings, admin, braille
# from routers import history

app = FastAPI(title="InfoX Assistive Reader API")

# CORS middleware — allow the admin panel and local dev to access the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",                    # Next.js local dev
        "https://infox-admin-alpha.vercel.app",     # Vercel preview deployments
        "https://admin.projectinfox.tech",          # Custom admin domain
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Example of how we will wire up the routes later:
app.include_router(auth.router, tags=["Authentication"])
app.include_router(settings.router, prefix="/settings", tags=["Settings"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(braille.router, tags=["Braille Scan"])

@app.get("/")
def health_check():
    """A simple endpoint to verify the server is running."""
    return {"status": "InfoX API is online and modular!"}
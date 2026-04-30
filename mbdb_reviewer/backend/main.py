"""FastAPI entry point for the MBDB reviewer backend."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import CORS_ORIGINS
from routes import fetch, validate

# Initialize FastAPI app
app = FastAPI(
    title="MBDB AI Reviewer API",
    description="Validation service for Molecular Biophysics Database metadata records",
    version="1.0.0"
)

# CORS middleware - allow frontend connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(fetch.router, tags=["MBDB Records"])
app.include_router(validate.router, tags=["Validation"])


# Health check endpoints
@app.get("/", tags=["Health"])
def read_root():
    """Root endpoint - API status check."""
    return {
        "message": "MBDB AI Reviewer API",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "ok"}

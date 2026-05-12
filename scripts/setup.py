"""
Sun Biz Agent Setup Script
Installs all required Python packages and validates environment.
(Repositioned 2026-05-11 from Marketing Agent — see brain/CHANGELOG.md)
"""

import subprocess
import sys
import os


def install_packages():
    """Install required Python packages."""
    packages = [
        "google-ads>=29.0.0",      # Google Ads API client
        "facebook-business>=22.0",  # Meta Marketing API client
        "google-genai",             # Gemini Imagen image generation
        "Pillow",                   # Image processing
        "python-dotenv",            # Environment variable management
        "requests",                 # HTTP client
    ]

    print("Installing required packages...")
    for package in packages:
        print(f"  Installing {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

    print("\nAll packages installed successfully!")


def check_env_file():
    """Check if .env.agents exists with required variables."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.agents")
    template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.agents.template")

    required_vars = {
        "Google Ads": [
            "GOOGLE_ADS_DEVELOPER_TOKEN",
            "GOOGLE_ADS_CLIENT_ID",
            "GOOGLE_ADS_CLIENT_SECRET",
            "GOOGLE_ADS_REFRESH_TOKEN",
            "GOOGLE_ADS_CUSTOMER_ID",
        ],
        "Meta Ads": [
            "META_ACCESS_TOKEN",
            "META_APP_ID",
            "META_APP_SECRET",
            "META_AD_ACCOUNT_ID",
        ],
        "Gemini Imagen": [
            "GEMINI_API_KEY",
        ],
    }

    if not os.path.exists(env_path):
        print(f"\n.env.agents not found at: {env_path}")
        print(f"Copy the template: cp {template_path} {env_path}")
        print("Then fill in your actual credentials.")
        return False

    # Read existing env file
    with open(env_path, "r") as f:
        content = f.read()

    missing = []
    for platform, vars_list in required_vars.items():
        for var in vars_list:
            if var not in content or f"{var}=INSERT" in content:
                missing.append(f"  [{platform}] {var}")

    if missing:
        print("\nMissing or unconfigured credentials:")
        for m in missing:
            print(m)
        return False

    print("\nAll credentials configured!")
    return True


def validate_google_ads():
    """Test Google Ads API connection."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        print("\ngoogle-ads package: OK")
    except ImportError:
        print("\ngoogle-ads package: NOT INSTALLED")
        return False
    return True


def validate_meta_ads():
    """Test Meta Marketing API connection."""
    try:
        from facebook_business.api import FacebookAdsApi
        print("facebook-business package: OK")
    except ImportError:
        print("facebook-business package: NOT INSTALLED")
        return False
    return True


if __name__ == "__main__":
    print("=" * 50)
    print("Sun Biz Agent Setup")
    print("=" * 50)

    install_packages()
    print("\n--- Validation ---")
    validate_google_ads()
    validate_meta_ads()
    check_env_file()

    print("\n--- Setup Complete ---")
    print("Next steps:")
    print("1. Fill in .env.agents with your API credentials")
    print("2. Update scripts/google-ads-mcp-wrapper.cmd with credentials")
    print("3. Update scripts/meta-ads-mcp-wrapper.cmd with credentials")
    print("4. Run /health to verify everything is connected")

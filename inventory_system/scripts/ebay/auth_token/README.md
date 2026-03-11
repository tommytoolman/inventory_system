# eBay OAuth Token System Guide

## Overview

The eBay OAuth system uses a three-token approach for secure API access. This guide explains each token type, how they work together, and how to manage them effectively.

## The Three Token Types

### 1. Authorization Code (The Visitor Pass)
- **What it is**: A temporary, one-time-use code that proves you just logged in
- **How long it lasts**: Only 5 minutes!
- **How you get it**: 
  1. eBay generates a special URL for you to visit
  2. You log into eBay and approve permissions
  3. eBay redirects you back with this code in the URL
- **What it looks like**: `v^1.1#i^1#f^0#r^1...` (very long, URL-encoded)
- **Purpose**: Exchange it quickly for a refresh token

### 2. Refresh Token (The Security Badge)
- **What it is**: A long-lived token that proves you're authorized
- **How long it lasts**: 18 months (about 540 days)
- **How you get it**: Exchange your authorization code for this
- **What it can do**: Generate new access tokens whenever needed
- **Storage**: Save this securely - it's your master key!
- **Important**: You can't use this directly to make API calls

### 3. Access Token (The Daily Key Card)
- **What it is**: The actual token you use to make API calls
- **How long it lasts**: Only 2 hours (120 minutes)
- **How you get it**: Use your refresh token to generate these
- **What it does**: This is what you send with every API request
- **Why so short?**: Security - if compromised, it expires quickly

## The Complete Authentication Flow

```
Step 1: Get Authorization URL
   ↓
Step 2: User logs in & approves (in browser)
   ↓
Step 3: Get Authorization Code (5 min expiry!)
   ↓
Step 4: Exchange for Refresh Token (lasts 18 months)
   ↓
Step 5: Use Refresh Token to get Access Token (lasts 2 hours)
   ↓
Step 6: Make API calls with Access Token
   ↓
Step 7: When Access Token expires, go back to Step 5
   ↓
Step 8: After 18 months, start over at Step 1
```

## Production vs Sandbox Environments

eBay maintains two completely separate systems:

### Production Environment
- Real eBay marketplace
- Real listings, real money
- URLs: 
  - Auth: `auth.ebay.com`
  - API: `api.ebay.com`
- Tokens stored in: `ebay_tokens.json`
- Used for: Actual business operations

### Sandbox Environment
- Test environment
- Fake listings, fake money
- URLs:
  - Auth: `auth.sandbox.ebay.com`
  - API: `api.sandbox.ebay.com`
- Tokens stored in: `ebay_sandbox_tokens.json`
- Used for: Testing and development
- **Important**: Sandbox tokens ≠ Production tokens!

## Common Issues and Solutions

### Issue 1: "My refresh token has 514 days left but it won't work!"
**Cause**: The refresh token might be valid BUT the access token expired
**Solution**: Use refresh token to get new access token

### Issue 2: "I keep getting invalid_grant errors"
**Possible Causes**:
- Your refresh token is for the wrong environment (sandbox vs prod)
- Your permissions changed and you need a completely new authorization
- The token file is corrupted or contains mixed environment tokens

**Solution**: Start fresh with new authorization

### Issue 3: "Why do I need so many tokens?"
**Answer**: Each serves a different security purpose:
- **Authorization Code**: Proves you just logged in (very temporary)
- **Refresh Token**: Your long-term credential (don't lose this!)
- **Access Token**: Your short-term API key (regenerate often)

## Token Storage Files

| Environment | Token File | Description |
|------------|------------|-------------|
| Production | `ebay_tokens.json` | Production refresh & access tokens |
| Sandbox | `ebay_sandbox_tokens.json` | Sandbox refresh & access tokens |

## Quick Command Reference

```bash
# Check token status
python manage_tokens.py status --sandbox

# Generate new authorization URL
python manage_tokens.py generate --sandbox

# Exchange authorization code for tokens
python manage_tokens.py exchange "PASTE_REDIRECT_URL_HERE" --sandbox

# Refresh access token
python manage_tokens.py refresh --sandbox

# Interactive full flow
python manage_tokens.py full --sandbox
```

## Important Security Notes

1. **Never commit token files to git** - Add them to `.gitignore`
2. **Refresh tokens are valuable** - Treat them like passwords
3. **Access tokens are temporary** - Don't hardcode them
4. **Environment separation** - Never mix sandbox and production tokens
5. **Permission changes** - If you change API scopes, you need new tokens

## Troubleshooting Checklist

When tokens aren't working:

1. ✓ Check you're using the right environment (sandbox vs production)
2. ✓ Verify token files exist and aren't corrupted
3. ✓ Confirm refresh token hasn't expired (540 days)
4. ✓ Check if access token needs refreshing (2 hours)
5. ✓ Ensure API permissions match what tokens were authorized for
6. ✓ Verify eBay application credentials are correct in `.env`

## Token Lifecycle Best Practices

1. **Initial Setup**: Generate tokens through full authorization flow
2. **Daily Use**: Access tokens auto-refresh from refresh token
3. **Monthly Check**: Verify refresh token still has >30 days
4. **Annual Renewal**: Plan to renew refresh tokens before 18 months
5. **Error Handling**: Catch token errors and refresh automatically

## Need Help?

If tokens still aren't working:
1. Delete existing token files
2. Run the full authorization flow
3. Ensure you're using correct eBay application credentials
4. Check eBay developer account for any notifications
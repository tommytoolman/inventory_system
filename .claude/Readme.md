# Tommy Checklist - WooCommerce Integration Package
## Complete Claude Code Prompt System for RIFF Technology

---

## 📦 What's In This Folder?

This folder contains everything needed to implement WooCommerce integration for RIFF Technology using Claude Code in VS Code. All files are designed to be copied directly into your `.claude` folder for context-aware development assistance.

---

## 📄 File Overview

### **01-MASTER-CLAUDE-CODE-PROMPT.md**
**Purpose:** Master prompt for Claude Code implementation
**When to Use:** Copy this into `.claude/project-instructions.md` or paste directly into Claude Code
**What It Does:**
- Provides complete context about the RIFF project
- Outlines all implementation requirements
- Defines code organisation structure
- Specifies authentication approach (Basic Auth for sandbox, OAuth for production)
- Details bidirectional sync requirements
- Includes error handling requirements
- Specifies UI toggle requirements

### **02-TECHNICAL-SPECIFICATIONS.md**
**Purpose:** Detailed API reference and technical details
**When to Use:** Reference for specific API endpoints, data structures, and error handling
**What It Does:**
- Complete WooCommerce REST API v3 endpoint documentation
- Request/response examples
- Data model schemas
- Error handling patterns
- Rate limiting information
- Python code examples
- Performance optimisation tips

### **03-TESTING-STRATEGY.md**
**Purpose:** Three-layer testing approach (Unit, Integration, Mock)
**When to Use:** When implementing tests for the integration
**What It Does:**
- Unit test examples with mocked responses
- Integration test patterns against sandbox
- Mock test setup with VCR.py
- Test fixtures and cleanup strategies
- CI/CD pipeline configuration
- Coverage goals and debugging tips

### **04-HANDOVER-OAUTH-IMPLEMENTATION.md**
**Purpose:** Documentation for the next developer who implements OAuth 1.0a
**When to Use:** After sandbox implementation is complete, before production deployment
**What It Does:**
- Explains what's been implemented (Basic Auth sandbox)
- Provides complete OAuth 1.0a implementation guide
- Includes signature generation code
- Webhook verification examples
- Security checklist
- Production deployment strategy
- Common OAuth issues and solutions

### **05-WOOCOMMERCE-INTEGRATION-GUIDE.html**
**Purpose:** Beautiful, comprehensive HTML guide for the integration
**When to Use:** Open in a browser for visual reference during development
**What It Does:**
- Step-by-step setup instructions
- Visual examples with syntax highlighting
- Troubleshooting section
- Testing checklist
- Security best practices
- Production deployment guide

---

## 🚀 How to Use These Files

### Step 1: Set Up Your Claude Code Context
```bash
# Navigate to your RIFF project root
cd /path/to/riff-technology

# Create .claude folder if it doesn't exist
mkdir -p .claude

# Copy the master prompt
cp /path/to/tommy-checklist/01-MASTER-CLAUDE-CODE-PROMPT.md .claude/project-instructions.md

# Optional: Copy technical specs for additional context
cp /path/to/tommy-checklist/02-TECHNICAL-SPECIFICATIONS.md .claude/woocommerce-api-reference.md
cp /path/to/tommy-checklist/03-TESTING-STRATEGY.md .claude/testing-guide.md
```

### Step 2: Open the HTML Guide
```bash
# Open in your default browser
open /path/to/tommy-checklist/05-WOOCOMMERCE-INTEGRATION-GUIDE.html

# Or on Windows
start /path/to/tommy-checklist/05-WOOCOMMERCE-INTEGRATION-GUIDE.html

# Or on Linux
xdg-open /path/to/tommy-checklist/05-WOOCOMMERCE-INTEGRATION-GUIDE.html
```

### Step 3: Start Claude Code in VS Code
1. Open your RIFF project in VS Code
2. Activate Claude Code extension
3. Claude Code will automatically read `.claude/project-instructions.md`
4. Start with: "Let's implement the WooCommerce integration as described in the project instructions"

### Step 4: Reference Files as Needed
- **During API implementation:** Refer to `02-TECHNICAL-SPECIFICATIONS.md`
- **During test writing:** Follow `03-TESTING-STRATEGY.md`
- **When stuck:** Check `05-WOOCOMMERCE-INTEGRATION-GUIDE.html` troubleshooting section

### Step 5: Handover for OAuth
Once sandbox implementation is complete:
1. Share `04-HANDOVER-OAUTH-IMPLEMENTATION.md` with the next developer
2. Highlight the OAuth implementation section
3. Ensure they understand Basic Auth is SANDBOX ONLY

---

## ⚙️ Environment Setup

### Required Environment Variables
Create a `.env` file in your RIFF project (DON'T commit this!):

```bash
# WooCommerce Sandbox Credentials
WC_STORE_URL=https://your-sandbox-store.com
WC_CONSUMER_KEY=ck_your_consumer_key_here
WC_CONSUMER_SECRET=cs_your_consumer_secret_here
WC_AUTH_METHOD=basic
WC_SANDBOX_MODE=true
WC_WEBHOOK_SECRET=your_webhook_secret

# Optional: Webhook endpoint
WC_WEBHOOK_URL=https://your-riff-api.com/webhooks/woocommerce
```

### Python Dependencies
```bash
pip install requests python-dotenv
pip install pytest pytest-cov  # For testing
pip install vcrpy  # For mock tests
```

---

## 🎯 Implementation Workflow

### Phase 1: Foundation (Days 1-2)
1. Claude Code explores existing RIFF codebase
2. Creates integration folder structure
3. Implements basic authentication client
4. Tests connection to sandbox WooCommerce site

**Claude Code Prompt:**
```
"Explore the RIFF codebase structure, then create the WooCommerce integration 
folder following the patterns used for other marketplace integrations (Reverb, 
eBay, Shopify). Start with the authentication client using Basic Auth for sandbox."
```

### Phase 2: Outbound Sync (Days 3-4)
1. Implement product creation in WooCommerce
2. Add product update functionality
3. Implement inventory sync
4. Test with real RIFF products

**Claude Code Prompt:**
```
"Implement the RIFF → WooCommerce sync. Products from RIFF should be created 
in WooCommerce with proper data mapping. Include the RIFF ID in meta_data so 
we can track which products came from RIFF."
```

### Phase 3: Inbound Sync (Days 5-6)
1. Implement product import from WooCommerce
2. Set up webhook receivers
3. Handle order notifications
4. Update RIFF inventory from WooCommerce sales

**Claude Code Prompt:**
```
"Implement WooCommerce → RIFF sync. Set up webhook endpoints to receive 
product updates and order notifications from WooCommerce. Include polling 
fallback if webhooks fail."
```

### Phase 4: UI & Controls (Day 7)
1. Add WooCommerce section to admin UI
2. Implement sandbox/production toggle
3. Add connection status indicators
4. Create manual sync triggers

**Claude Code Prompt:**
```
"Add WooCommerce UI components to the RIFF admin interface. Include a 
'Production Mode: ON/OFF' toggle button, connection status indicator, 
and manual sync trigger button."
```

### Phase 5: Testing (Days 8-9)
1. Write unit tests
2. Write integration tests
3. Write mock tests
4. Run full test suite

**Claude Code Prompt:**
```
"Implement the three-layer testing strategy from the testing guide. Start with 
unit tests for data mapping and authentication, then integration tests against 
the sandbox, then mock tests for edge cases."
```

---

## ⚠️ Critical Reminders

### For Development Phase (Current)
✅ **DO:**
- Use Basic Auth over HTTPS
- Test in sandbox environment
- Store credentials in environment variables
- Mark all sandbox code clearly
- Include extensive logging

❌ **DON'T:**
- Use with production data
- Commit credentials to Git
- Deploy to production with Basic Auth
- Skip error handling
- Ignore rate limits

### For Production Phase (Future)
✅ **MUST:**
- Implement OAuth 1.0a (see handover doc)
- Use secure secret management
- Verify webhook signatures
- Enable SSL verification
- Set up monitoring and alerts

---

## 📊 Success Criteria

### Sandbox Implementation Complete When:
- [ ] Claude Code successfully explores RIFF codebase
- [ ] Integration connects to WooCommerce sandbox
- [ ] Products sync from RIFF → WooCommerce
- [ ] Products import from WooCommerce → RIFF
- [ ] Stock levels stay in sync
- [ ] UI toggle for sandbox/production mode works
- [ ] All three test layers pass
- [ ] Code is well-documented with inline comments
- [ ] Handover documentation updated

### Ready for OAuth Implementation When:
- [ ] All sandbox testing complete
- [ ] No known bugs in sync logic
- [ ] Error handling thoroughly tested
- [ ] Rate limiting respected
- [ ] Webhook endpoints functional
- [ ] UI shows correct mode indicators
- [ ] Next developer briefed on OAuth requirements

---

## 🐛 Troubleshooting

### Claude Code Can't Find Project Context
**Solution:** Ensure files are in `.claude/` folder and named correctly
```bash
ls -la .claude/
# Should show project-instructions.md
```

### Claude Code Doesn't Follow Instructions
**Solution:** Be explicit in prompts and reference the master prompt
```
"Following the instructions in project-instructions.md, implement the 
WooCommerce client with Basic Auth as specified."
```

### Integration Tests Fail
**Solution:** Check environment variables are set
```bash
echo $WC_STORE_URL
echo $WC_CONSUMER_KEY
# Should print your credentials
```

### API Returns 401 Unauthorised
**Solution:** 
1. Verify credentials in WooCommerce admin
2. Check user has administrator permissions
3. Ensure HTTPS is being used
4. Try query string auth if header auth fails

---

## 📚 Additional Resources

### WooCommerce Official Docs
- [REST API v3 Documentation](https://woocommerce.github.io/woocommerce-rest-api-docs/)
- [Authentication Guide](https://woocommerce.com/document/woocommerce-rest-api/)
- [Webhooks Documentation](https://woocommerce.com/document/webhooks/)

### Python Libraries
- [requests](https://docs.python-requests.org/) - HTTP library
- [python-dotenv](https://pypi.org/project/python-dotenv/) - Environment variables
- [pytest](https://docs.pytest.org/) - Testing framework
- [vcrpy](https://vcrpy.readthedocs.io/) - HTTP interaction recording

### Tools
- [Postman](https://www.postman.com/) - API testing
- [ngrok](https://ngrok.com/) - Webhook testing locally
- [Local by Flywheel](https://localwp.com/) - Local WordPress development

---

## 💡 Pro Tips

### For Faster Development
1. **Use the HTML guide** as a visual reference (open in split screen)
2. **Copy code examples** from technical specs directly
3. **Run tests frequently** - catch issues early
4. **Use Postman first** to verify API endpoints work before coding
5. **Enable verbose logging** during development

### For Better Results with Claude Code
1. **Reference specific sections** of the master prompt
2. **Ask for incremental changes** rather than big rewrites
3. **Request tests** alongside implementation
4. **Ask for explanations** of complex authentication logic
5. **Have Claude review** its own code for security issues

### For Smooth Handover
1. **Document any deviations** from the master prompt
2. **Note any WooCommerce quirks** discovered during testing
3. **Update environment variable list** if any added
4. **Record any API rate limits** encountered
5. **List any additional dependencies** installed

---

## ✅ Final Checklist

Before considering the implementation complete:

**Code Quality:**
- [ ] Follows existing RIFF code patterns
- [ ] Uses British English in user-facing text
- [ ] Has comprehensive docstrings
- [ ] Includes type hints
- [ ] No hardcoded credentials

**Functionality:**
- [ ] Bidirectional sync works
- [ ] Error handling robust
- [ ] Rate limiting respected
- [ ] Webhook handlers secure
- [ ] UI toggle functional

**Testing:**
- [ ] 90%+ unit test coverage
- [ ] Integration tests pass against sandbox
- [ ] Mock tests cover edge cases
- [ ] Performance tested with 1000+ products
- [ ] Error scenarios tested

**Documentation:**
- [ ] README created in integration folder
- [ ] Environment variables documented
- [ ] API quirks noted
- [ ] Future OAuth work clearly marked
- [ ] Handover doc updated

**Security:**
- [ ] Credentials not in version control
- [ ] Sandbox-only warnings in place
- [ ] OAuth TODOs clearly marked
- [ ] Security logging enabled
- [ ] SSL verification enforced

---

## 🎉 You're Ready!

Everything you need is in this folder. Copy the files to your project, follow the implementation workflow, and let Claude Code guide you through building a robust WooCommerce integration for RIFF Technology.

**Remember:** This implementation is for sandbox/development only. OAuth 1.0a must be implemented before production deployment with real customer data.

Good luck! 🚀🎸

---

**Questions?** 
Refer back to the specific files:
- Technical questions → `02-TECHNICAL-SPECIFICATIONS.md`
- Testing questions → `03-TESTING-STRATEGY.md`
- OAuth questions → `04-HANDOVER-OAUTH-IMPLEMENTATION.md`
- Setup questions → `05-WOOCOMMERCE-INTEGRATION-GUIDE.html`
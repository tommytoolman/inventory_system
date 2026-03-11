# Toast/Notification Standardisation

*Created: 2026-01-03*

## Overview

The codebase has inconsistent toast/notification implementations across templates. This document captures the audit findings and proposed standardisation approach.

## What is a "Toast"?

A toast is a small notification message that pops up (usually in a corner) and auto-dismisses - like toast popping out of a toaster. Same thing as notification/flash message/alert banner.

## Current Global Function

A global notification function already exists in `base.html` (lines 301-320):

```javascript
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 px-4 py-2 text-sm rounded-md shadow-md z-50 transition-all duration-300 ${
        type === 'success' ? 'bg-green-50 text-green-800 border border-green-200' :
        type === 'error' ? 'bg-red-50 text-red-800 border border-red-200' :
        'bg-gray-50 text-gray-800 border border-gray-200'
    }`;
    notification.style.maxWidth = '320px';
    notification.innerHTML = message.replace('\n', '<br>');
    document.body.appendChild(notification);

    // Remove after 3 seconds
    setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transform = 'translateX(100%)';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}
```

**Features:**
- Fixed position: top-right corner
- Types: `success` (green), `error` (red), `info` (grey default)
- Auto-dismisses after 3 seconds with slide-out animation
- Max width: 320px

## Current Implementations Audit

| Location | Type | Auto-dismiss | Notes |
|----------|------|--------------|-------|
| `base.html:301-320` | Global `showNotification()` | 3s | The standard to adopt |
| `inventory/list.html:5-16` | Server flash message | 10s | Jinja2 `{% if message %}`, different timing |
| `inventory/detail.html:174-197` | Platform status alerts | 500ms fade | Inline JS, different animation |
| `inventory/add.html:4707` | Product created | 3s | Inline notification, duplicates global |
| `inventory/add.html:5126` | Creation + redirect | 3s | Inline notification, duplicates global |
| `inventory/add.html:5805` | "Images cleared" | 2s | Inline notification, different timing |
| `inventory/add.html:5864` | "Images selected" | 2s | Inline notification, different timing |

## Issues

1. **Inconsistent timing** - ranges from 2s to 10s across different toasts
2. **No shared component** - `base.html` has global function but `add.html` creates its own inline notifications
3. **Different styling** - some use different colour schemes or animations
4. **Server flash message persistence** - `list.html` uses Jinja2 message which can persist on refresh if session isn't cleared

## Proposed Standardisation

### 1. Use `showNotification()` everywhere

Refactor all inline notification code to call the global function:

```javascript
// Instead of creating inline elements:
showNotification('Product created successfully!', 'success');
showNotification('Failed to save changes', 'error');
showNotification('3 images selected', 'info');
```

### 2. Standardise timing

| Type | Duration | Use case |
|------|----------|----------|
| `info` | 3s | General information |
| `success` | 3s | Action completed |
| `error` | 5s | Errors (longer so user can read) |

### 3. Add optional dismiss button

For longer messages or errors, add an X button:

```javascript
function showNotification(message, type = 'info', dismissible = false) {
    // ... existing code ...
    if (dismissible) {
        // Add close button
    }
}
```

### 4. Server-side flash messages

Update `list.html` and similar templates to use consistent styling and auto-dismiss behaviour matching the JS notifications.

## Files to Update

1. `app/templates/base.html` - Enhance global function (optional dismiss button, configurable timing)
2. `app/templates/inventory/add.html` - Replace ~4 inline notification implementations
3. `app/templates/inventory/list.html` - Align server flash message styling/timing
4. `app/templates/inventory/detail.html` - Replace platform status inline notifications

## Implementation Steps

1. [ ] Enhance `showNotification()` in base.html (add dismiss option, error timing)
2. [ ] Refactor `inventory/add.html` to use global function
3. [ ] Refactor `inventory/detail.html` to use global function
4. [ ] Align `inventory/list.html` flash message styling
5. [ ] Test all notification scenarios across pages

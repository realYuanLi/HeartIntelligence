# Device Settings Page
**Date**: 2026-04-05  |  **Status**: Completed

## What Was Built
A new "Devices" settings page that previews upcoming wearable and health app integrations via MyDataHelps. The page lists supported platforms (Apple Health, Google Health Connect, Fitbit, Garmin, Oura), explains the future OAuth-based connection flow, and is marked "Coming Soon." It gives users visibility into planned device support while the backend integration is still in progress.

## Architecture
The page follows the existing settings sub-navigation pattern. A Flask route in `cron_jobs.py` serves the template with `settings_section="devices"` so the subnav tab highlights correctly. The sidebar in `base.html` includes a Devices entry with a smartphone icon, and the client-side routing script maps `/settings/devices` to the correct sidebar state.

## Key Files
| File | Purpose |
|------|---------|
| `templates/settings_devices.html` | Full page template: overview card, supported platforms list, how-it-works steps |
| `functions/cron_jobs.py` (line 538) | `settings_devices_page()` route behind `@login_required` |
| `templates/base.html` (line 233) | Sidebar entry with device icon and description |
| `templates/base.html` (line 283) | Client-side routing to highlight sidebar item on `/settings/devices` |

## Technical Decisions
- **Reused existing card components** (`cron-job-form-card`, `job-card`) instead of creating new CSS, keeping the settings pages visually consistent.
- **Route lives in `cron_bp`** alongside other settings routes rather than a new blueprint, avoiding unnecessary module proliferation for a static page.
- **"Coming Soon" badge** signals the feature is planned without exposing non-functional connect buttons.

## Usage
```
# Navigate to the Devices settings page
http://localhost:5001/settings/devices

# Or click Settings > Devices in the sidebar
```

## Testing
1. Log in and navigate to `/settings/devices` -- page should render with subnav tab active.
2. Verify all five platform cards display with correct names and descriptions.
3. Check sidebar highlights the Devices item when on this path.
4. Confirm unauthenticated access redirects to login.

## Known Limitations
- **No functional device connections yet** -- the page is informational only; MyDataHelps OAuth integration is not wired up.
- **No per-user device state** -- there is no database model or API for storing connected devices.
- **Platform list is static HTML** -- adding or removing supported platforms requires a template edit.

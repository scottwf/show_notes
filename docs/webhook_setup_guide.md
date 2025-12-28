# Webhook Setup Guide for Automatic Library Syncing

## Overview

ShowNotes now supports automatic library synchronization through webhooks from Radarr and Sonarr. This eliminates the need for manual syncing and ensures your ShowNotes database is always up to date when content is added, updated, or removed.

## Benefits

- **Automatic Updates**: No more manual syncing required
- **Real-time Sync**: Database updates immediately when content changes
- **Background Processing**: Syncs run in the background without blocking webhook responses
- **Comprehensive Coverage**: Handles downloads, deletions, renames, and health checks

## Supported Events

### Sonarr Webhook Events
- **Download**: When episodes are downloaded
- **Series**: When series are added/updated (generic)
- **SeriesAdd**: When a new series is added (Sonarr v3+)
- **SeriesDelete**: When a series is deleted
- **Episode**: When episodes are added/updated
- **EpisodeFileDelete**: When episode files are deleted
- **Rename**: When files are renamed
- **Delete**: When files are deleted
- **Health**: Health check events (optional, for periodic syncs)
- **Test**: Test events

### Radarr Webhook Events
- **Download**: When movies are downloaded
- **Movie**: When movies are added/updated (generic)
- **MovieAdded**: When a new movie is added (Radarr v3+)
- **MovieDelete**: When a movie is deleted
- **MovieFileDelete**: When movie files are deleted
- **Rename**: When files are renamed
- **Delete**: When files are deleted
- **Health**: Health check events (optional, for periodic syncs)
- **Test**: Test events

## Setup Instructions

### 1. Sonarr Webhook Configuration

1. **Open Sonarr Web Interface**
   - Navigate to your Sonarr instance in your browser

2. **Go to Settings**
   - Click on the **Settings** tab in the top navigation

3. **Navigate to Connect**
   - In the left sidebar, click on **Connect**

4. **Add New Connection**
   - Click the **+** button to add a new connection
   - Select **Webhook** from the list of available connections

5. **Configure the Webhook**
   - **Name**: `ShowNotes`
   - **URL**: `https://your-shownotes-domain.com/sonarr/webhook`
   - **Method**: `POST` (important: change from default PUT to POST)
   - **Username**: (leave empty)
   - **Password**: (leave empty)
   - **On Grab**: ✓ (optional, for tracking download requests)
   - **On Download**: ✓ (checked - triggers episode sync)
   - **On Series Add**: ✓ (checked - important for new shows!)
   - **On Series Delete**: ✓ (checked)
   - **On Episode File Delete**: ✓ (checked)
   - **On Episode File Delete For Upgrade**: ✓ (checked)
   - **On Rename**: ✓ (checked)
   - **On Health Issue**: ✓ (checked, optional)

6. **Save Configuration**
   - Click **Save** to activate the webhook

### 2. Radarr Webhook Configuration

1. **Open Radarr Web Interface**
   - Navigate to your Radarr instance in your browser

2. **Go to Settings**
   - Click on the **Settings** tab in the top navigation

3. **Navigate to Connect**
   - In the left sidebar, click on **Connect**

4. **Add New Connection**
   - Click the **+** button to add a new connection
   - Select **Webhook** from the list of available connections

5. **Configure the Webhook**
   - **Name**: `ShowNotes`
   - **URL**: `https://your-shownotes-domain.com/radarr/webhook`
   - **Method**: `POST` (important: change from default PUT to POST)
   - **Username**: (leave empty)
   - **Password**: (leave empty)
   - **On Grab**: ✓ (optional, for tracking download requests)
   - **On Download**: ✓ (checked - triggers movie sync)
   - **On Movie Added**: ✓ (checked - important for new movies!)
   - **On Movie Delete**: ✓ (checked)
   - **On Movie File Delete**: ✓ (checked)
   - **On Movie File Delete For Upgrade**: ✓ (checked)
   - **On Rename**: ✓ (checked)
   - **On Health Issue**: ✓ (checked, optional)

6. **Save Configuration**
   - Click **Save** to activate the webhook

## Webhook URLs

The webhook URLs are automatically generated based on your ShowNotes installation:

- **Sonarr Webhook**: `{{ site_url }}/sonarr/webhook`
- **Radarr Webhook**: `{{ site_url }}/radarr/webhook`

You can find these URLs in the **Settings** page of your ShowNotes admin interface.

## How It Works

1. **Event Trigger**: When Radarr or Sonarr performs an action (download, delete, rename, etc.), it sends a webhook notification to ShowNotes

2. **Background Processing**: ShowNotes receives the webhook and immediately starts a background sync process

3. **Database Update**: The sync process fetches the latest data from Radarr/Sonarr and updates the ShowNotes database

4. **Logging**: All webhook events and sync operations are logged for monitoring and debugging

## Monitoring and Troubleshooting

### Check Webhook Status

1. **View Logs**: Check the admin logs page for webhook activity
2. **Test Webhooks**: Use the "Test" event in Radarr/Sonarr to verify webhook delivery
3. **Monitor Sync Status**: Check the admin dashboard for recent sync activity

### Common Issues

1. **Webhook Not Received**
   - Verify the webhook URL is correct
   - Check that ShowNotes is accessible from your Radarr/Sonarr server
   - Ensure firewall/network allows the connection
   - **Important**: Make sure the HTTP Method is set to `POST`, not `PUT` (the default)

2. **Sync Not Triggered**
   - Verify the correct events are selected in the webhook configuration
   - Check ShowNotes logs for any errors
   - Ensure Radarr/Sonarr API credentials are correct
   - Verify username and password fields are left empty (no authentication required)

3. **Background Sync Fails**
   - Check ShowNotes application logs
   - Verify database permissions
   - Ensure sufficient system resources

### Log Messages to Look For

**Successful Webhook Reception:**
```
Sonarr webhook received: {"eventType": "Download", ...}
Sonarr webhook event 'Download' detected, triggering library sync
Sonarr library sync initiated in background
```

**Successful Sync Completion:**
```
Sonarr webhook-triggered sync completed: 150 shows processed
```

**Error Messages:**
```
Error processing Sonarr webhook: [error details]
Failed to trigger Sonarr sync from webhook: [error details]
```

## Security Considerations

- **HTTPS**: Always use HTTPS for webhook URLs in production
- **Network Access**: Ensure only your Radarr/Sonarr instances can access the webhook endpoints
- **Logging**: Webhook payloads are logged for debugging; consider log rotation for privacy
- **Rate Limiting**: Consider implementing rate limiting if needed

## Performance Impact

- **Background Processing**: Webhook-triggered syncs run in background threads
- **Non-blocking**: Webhook responses are immediate; syncs don't block the response
- **Efficient**: Only syncs when content actually changes
- **Resource Usage**: Syncs use the same resources as manual syncs

## Migration from Manual Syncing

1. **Set up webhooks** following the instructions above
2. **Test the setup** by triggering a download or rename in Radarr/Sonarr
3. **Monitor for a few days** to ensure everything works correctly
4. **Keep manual sync buttons** as a backup for troubleshooting

## Troubleshooting Checklist

- [ ] Webhook URL is correct and accessible
- [ ] All required events are selected in webhook configuration
- [ ] ShowNotes is running and accessible
- [ ] Database has proper permissions
- [ ] Logs show webhook reception
- [ ] Background sync processes complete successfully
- [ ] Database is updated with new content

## Support

If you encounter issues with webhook setup:

1. Check the ShowNotes application logs
2. Verify webhook configuration in Radarr/Sonarr
3. Test webhook delivery using the "Test" event
4. Check network connectivity between services
5. Review this documentation for common solutions

The webhook system is designed to be robust and self-healing, but manual sync buttons remain available as a fallback option. 
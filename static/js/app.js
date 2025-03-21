document.addEventListener('DOMContentLoaded', function() {
    // Library link
    const libraryLink = document.getElementById('library-link');
    if (libraryLink) {
        libraryLink.addEventListener('click', function(e) {
            e.preventDefault();
            window.location.href = '/library';
        });
    }

    // Global status checking
    window.checkGlobalAnalysisStatus = function() {
        const statusIndicator = document.getElementById('global-analysis-status');
        
        if (!statusIndicator) return;
        
        let lastMetadataStatus = null;
        let lastAnalysisStatus = null;
        let lastQuickScanStatus = null;
        let pollInterval = 3000; // Start with 3 seconds between polls
        let consecutiveErrors = 0;
        let timer = null;
        
        function checkStatus() {
            // Use Promise.all to make parallel requests for better performance
            Promise.all([
                fetch('/api/analysis/status').then(r => r.json()),
                fetch('/api/metadata-update/status').then(r => r.json()),
                fetch('/api/quick-scan/status').then(r => r.json())
            ])
            .then(([analysisData, metadataData, quickScanData]) => {
                // Reset error counter on success
                consecutiveErrors = 0;
                
                // Update DOM only if status has changed to reduce repaints
                const analysisChanged = JSON.stringify(analysisData) !== JSON.stringify(lastAnalysisStatus);
                const metadataChanged = JSON.stringify(metadataData) !== JSON.stringify(lastMetadataStatus);
                const quickScanChanged = JSON.stringify(quickScanData) !== JSON.stringify(lastQuickScanStatus);
                
                if (!analysisChanged && !metadataChanged && !quickScanChanged) {
                    // No changes, skip DOM update but continue polling
                    scheduleNextPoll();
                    return;
                }
                
                // Save the current status for future comparison
                lastAnalysisStatus = analysisData;
                lastMetadataStatus = metadataData;
                lastQuickScanStatus = quickScanData;
                
                // First check if analysis is running (takes priority)
                if (analysisData.running) {
                    // Update the status indicator
                    statusIndicator.classList.add('active');
                    
                    // Simplified HTML update to reduce parsing time
                    statusIndicator.innerHTML = 
                        '<div class="status-icon pulse"></div>' +
                        '<div class="status-text">Analysis running (' + 
                        analysisData.percent_complete + '%)</div>';
                } 
                // Then check if quick scan is running
                else if (quickScanData.running) {
                    statusIndicator.classList.add('active');
                    
                    // Build a concise status message
                    let statusText = 'Quick scanning files (' + quickScanData.percent_complete + '%)';
                    
                    // Create a simpler DOM update
                    const statusHTML = 
                        '<div class="status-icon pulse"></div>' +
                        '<div class="status-text">' + statusText + '</div>' +
                        '<div class="progress-bar">' +
                        '<div class="progress-fill" style="width: ' + 
                        quickScanData.percent_complete + '%"></div></div>';
                    
                    statusIndicator.innerHTML = statusHTML;
                }
                // Then check if metadata update is running
                else if (metadataData.running) {
                    statusIndicator.classList.add('active');
                    
                    // Build a more concise status message
                    let statusText = 'Updating metadata (' + metadataData.percent_complete + '%)';
                    
                    // Create a simpler DOM update
                    const statusHTML = 
                        '<div class="status-icon pulse"></div>' +
                        '<div class="status-text">' + statusText + '</div>' +
                        '<div class="progress-bar">' +
                        '<div class="progress-fill" style="width: ' + 
                        metadataData.percent_complete + '%"></div></div>';
                    
                    statusIndicator.innerHTML = statusHTML;
                } else {
                    statusIndicator.classList.remove('active');
                    statusIndicator.innerHTML = '';
                }
                
                // Schedule next poll
                scheduleNextPoll();
            })
            .catch(error => {
                console.error('Error checking global status:', error);
                consecutiveErrors++;
                
                // Increase poll interval on errors to reduce server load
                if (consecutiveErrors > 3) {
                    pollInterval = Math.min(pollInterval * 1.5, 10000); // Max 10 seconds
                }
                
                // Even on error, continue checking
                scheduleNextPoll();
            });
        }
        
        function scheduleNextPoll() {
            // Clear any existing timer
            if (timer) clearTimeout(timer);
            
            // Schedule next poll
            timer = setTimeout(checkStatus, pollInterval);
        }
        
        // Start checking
        checkStatus();
        
        // Return a function to cancel polling
        return function stopPolling() {
            if (timer) clearTimeout(timer);
        };
    };

    // Initialize global status checking on page load
    window.globalStatusChecker = window.checkGlobalAnalysisStatus();
});

// Global status checking
let metadataStatusChecker = null;

function setupGlobalStatusChecking() {
    // Check immediately on page load
    checkBackgroundTasks();
    
    // Then check periodically
    metadataStatusChecker = setInterval(checkBackgroundTasks, 5000);
}

function checkBackgroundTasks() {
    // Check metadata update status
    fetch('/api/metadata-update/status').then(r => r.json())
        .then(data => {
            const container = document.getElementById('global-status-container');
            const metadataTask = document.getElementById('metadata-task');
            const progressFill = metadataTask.querySelector('.task-progress-fill');
            const infoSpan = metadataTask.querySelector('.task-info');
            
            if (data.running) {
                // Show the status container and task
                container.style.display = 'block';
                metadataTask.style.display = 'block';
                
                // Update progress
                progressFill.style.width = `${data.percent_complete}%`;
                
                // Update info text
                const processed = data.processed_tracks || 0;
                const total = data.total_tracks || 0;
                const updated = data.updated_tracks || 0;
                infoSpan.textContent = `${processed}/${total} (${updated} updated)`;
            } else if (container.style.display === 'block' && !data.running) {
                // If we were showing a task that's now complete
                if (data.error) {
                    infoSpan.textContent = `Error: ${data.error}`;
                    setTimeout(() => {
                        metadataTask.style.display = 'none';
                        // Hide container if no active tasks
                        if (!document.querySelector('.task-status[style="display: block;"]')) {
                            container.style.display = 'none';
                        }
                    }, 10000); // Hide after 10 seconds
                } else if (data.processed_tracks > 0) {
                    // Show completion message
                    progressFill.style.width = '100%';
                    infoSpan.textContent = `Complete! ${data.updated_tracks} of ${data.total_tracks} updated`;
                    setTimeout(() => {
                        metadataTask.style.display = 'none';
                        // Hide container if no active tasks
                        if (!document.querySelector('.task-status[style="display: block;"]')) {
                            container.style.display = 'none';
                        }
                    }, 10000); // Hide after 10 seconds
                } else {
                    // Just hide if no activity
                    metadataTask.style.display = 'none';
                    // Hide container if no active tasks
                    if (!document.querySelector('.task-status[style="display: block;"]')) {
                        container.style.display = 'none';
                    }
                }
            }
        })
        .catch(err => console.error('Error checking metadata status:', err));
    
    // Add other background task checks here if needed
}

// Setup on page load
document.addEventListener('DOMContentLoaded', setupGlobalStatusChecking);

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    if (metadataStatusChecker) {
        clearInterval(metadataStatusChecker);
    }
});
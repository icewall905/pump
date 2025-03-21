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
        
        if (!statusIndicator) return null;
        
        let lastMetadataStatus = null;
        let lastAnalysisStatus = null;
        let lastQuickScanStatus = null;
        let pollInterval = 3000; // Start with 3 seconds between polls
        let consecutiveErrors = 0;
        let timer = null;
        let isNavigating = false;
        
        // Function to pause polling during navigation
        window.pauseStatusPolling = function() {
            isNavigating = true;
            console.log('Status polling paused for navigation');
            if (timer) clearTimeout(timer);
        };
        
        // Function to resume polling after navigation
        window.resumeStatusPolling = function() {
            isNavigating = false;
            console.log('Status polling resumed');
            checkStatus();
        };
        
        function checkStatus() {
            // Skip checking if we're in the middle of navigation
            if (isNavigating) {
                scheduleNextPoll();
                return;
            }
            
            // Use Promise.all to make parallel requests for better performance
            Promise.all([
                fetch('/api/analysis/status').then(r => r.json()).catch(() => ({})),
                fetch('/api/metadata-update/status').then(r => r.json()).catch(() => ({})),
                fetch('/api/quick-scan/status').then(r => r.json()).catch(() => ({}))
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
                
                // Only update the UI if something is running
                if ((analysisData.running || metadataData.running || quickScanData.running) && !isNavigating) {
                    statusIndicator.classList.add('active');
                    
                    // Simplified DOM update - determine the most important status to show
                    let statusHTML = '';
                    if (analysisData.running) {
                        statusHTML = 
                            '<div class="status-icon pulse"></div>' +
                            '<div class="status-text">Analysis running (' + 
                            analysisData.percent_complete + '%)</div>';
                    } else if (quickScanData.running) {
                        statusHTML = 
                            '<div class="status-icon pulse"></div>' +
                            '<div class="status-text">Quick scanning files (' + 
                            quickScanData.percent_complete + '%)</div>';
                    } else if (metadataData.running) {
                        statusHTML = 
                            '<div class="status-icon pulse"></div>' +
                            '<div class="status-text">Updating metadata (' + 
                            metadataData.percent_complete + '%)</div>';
                    }
                    
                    if (statusHTML) {
                        statusIndicator.innerHTML = statusHTML;
                    } else {
                        statusIndicator.classList.remove('active');
                    }
                } else {
                    statusIndicator.classList.remove('active');
                    statusIndicator.innerHTML = '';
                }
                
                // Schedule next poll with adaptive interval
                if (analysisData.running || metadataData.running || quickScanData.running) {
                    // Poll more frequently if tasks are running
                    pollInterval = 3000;
                } else {
                    // Poll less frequently when idle
                    pollInterval = 8000;
                }
                
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
            // Clear existing timer to prevent overlap
            if (pollTimer) clearTimeout(pollTimer);
            
            // Schedule next check
            pollTimer = setTimeout(checkAllStatuses, pollInterval);
        }
        
        // Debounce function to avoid excessive event handling
        function debounce(func, wait) {
            let timeout;
            return function() {
                const context = this, args = arguments;
                clearTimeout(timeout);
                timeout = setTimeout(() => func.apply(context, args), wait);
            };
        }
        
        // Return the control functions
        return {
            stop: function() {
                if (timer) clearTimeout(timer);
            },
            pause: window.pauseStatusPolling,
            resume: window.resumeStatusPolling
        };
    };

    // Remove all other global status checking functions and intervals
    if (window.metadataStatusChecker) {
        clearInterval(window.metadataStatusChecker);
        window.metadataStatusChecker = null;
    }

    // Create a single centralized status checker
    window.statusChecker = window.checkGlobalAnalysisStatus();
});
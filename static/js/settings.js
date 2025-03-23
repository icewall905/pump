// Add this at the beginning of the file
window.initSettingsPage = function() {
    // Initialize settings page functions
    initLibraryManagement();
    initMetadataControls();
    initCacheControls();
    initDatabasePerformanceSettings();
    
    // Create toast container if it doesn't exist
    if (!document.getElementById('toast-container')) {
        const toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        document.body.appendChild(toastContainer);
    }
    
    // Check analysis status immediately
    updateAnalysisStatus();
    
    // Save current page to session storage
    sessionStorage.setItem('currentPage', 'settings');
    
    // Setup scheduled task display
    const scheduleFrequency = document.getElementById('schedule_frequency');
    if (scheduleFrequency) {
        scheduleFrequency.addEventListener('change', updateNextRunDisplay);
        // Initial display
        updateNextRunDisplay();
    }
};

// When document is ready
document.addEventListener('DOMContentLoaded', () => {
    window.initSettingsPage();
});

// Initialize library management functions
function initLibraryManagement() {
    const savePathBtn = document.getElementById('save-music-path');
    const analyzeBtn = document.getElementById('analyze-button');
    const quickScanBtn = document.getElementById('quick-scan-btn');
    
    if (savePathBtn) {
        savePathBtn.addEventListener('click', function() {
            const path = document.getElementById('music-directory').value;
            const recursive = document.getElementById('recursive-scan').checked;
            
            if (!path) {
                showMessage('Please enter a music folder path', 'error');
                return;
            }
            
            // Show loading state
            savePathBtn.disabled = true;
            savePathBtn.textContent = 'Saving...';
            
            // Save the path
            fetch('/api/settings/save_music_path', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    path: path,
                    recursive: recursive
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showMessage('Music path saved successfully', 'success');
                } else {
                    showMessage(`Error: ${data.message || 'Unknown error'}`, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showMessage('Failed to save music path', 'error');
            })
            .finally(() => {
                // Reset button
                savePathBtn.disabled = false;
                savePathBtn.textContent = 'Save Path';
            });
        });
    }
    
    if (analyzeBtn) {
        analyzeBtn.addEventListener('click', startFullAnalysis);
    }
    
    if (quickScanBtn) {
        quickScanBtn.addEventListener('click', startQuickScan);
    }
}

function initMetadataControls() {
    const updateMetadataBtn = document.getElementById('update-metadata-btn');
    const updateLastfmBtn = document.getElementById('update-lastfm-btn');
    const updateSpotifyBtn = document.getElementById('update-spotify-btn');
    
    if (updateMetadataBtn) {
        updateMetadataBtn.addEventListener('click', function() {
            startMetadataUpdate();
        });
    }
    
    if (updateLastfmBtn) {
        updateLastfmBtn.addEventListener('click', function() {
            updateArtistImages('lastfm');
        });
    }
    
    if (updateSpotifyBtn) {
        updateSpotifyBtn.addEventListener('click', function() {
            updateArtistImages('spotify');
        });
    }
}

function startMetadataUpdate() {
    const skipExisting = document.getElementById('skip-existing-metadata').checked;
    
    fetch('/api/update-metadata', { 
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            skip_existing: skipExisting
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            pollMetadataStatus();
        }
    })
    .catch(err => console.error(err));
}

function pollMetadataStatus() {
    fetch('/api/metadata-update/status')
        .then(res => res.json())
        .then(status => {
            if (status.running) {
                // ...existing code or minimal UI update...
                setTimeout(pollMetadataStatus, 2000);
            } else {
                // ...existing code or clear indicator...
            }
        })
        .catch(err => console.error(err));
}

function initCacheControls() {
    const clearCacheBtn = document.getElementById('clear-cache-btn');
    const refreshStatsBtn = document.getElementById('refresh-stats-btn');
    const refreshLibraryStatsBtn = document.getElementById('refresh-library-stats-btn');
    
    if (clearCacheBtn) {
        clearCacheBtn.addEventListener('click', function() {
            clearCache();
        });
    }
    
    if (refreshStatsBtn) {
        refreshStatsBtn.addEventListener('click', function() {
            loadCacheStats();
        });
    }
    
    if (refreshLibraryStatsBtn) {
        refreshLibraryStatsBtn.addEventListener('click', function() {
            updateLibraryStats();
        });
    }
    
    // Load cache stats initially
    loadCacheStats();
    
    // Load library stats initially
    updateLibraryStats();
}

// Start the full analysis process
function startFullAnalysis() {
    const analyzeBtn = document.getElementById('analyze-button');
    const path = document.getElementById('music-directory').value;
    const recursive = document.getElementById('recursive-scan').checked;
    
    if (!path) {
        showMessage('Please enter and save a music folder path first', 'error');
        return;
    }
    
    // Show loading state
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = 'Starting Analysis...';
    
    // First save the path
    fetch('/api/settings/save_music_path', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            path: path,
            recursive: recursive
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Now start the analysis
            return fetch('/analyze', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    folder_path: path,
                    recursive: recursive
                })
            });
        } else {
            throw new Error(data.message || 'Failed to save path');
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showMessage('Analysis started successfully', 'success');
            updateAnalysisStatus(); // Start polling for status updates
            
            // Also update the global status indicator in layout.html
            if (window.checkGlobalAnalysisStatus) {
                window.checkGlobalAnalysisStatus();
            }
        } else {
            showMessage(`Error: ${data.error || 'Unknown error'}`, 'error');
            analyzeBtn.disabled = false;
            analyzeBtn.textContent = 'Full Analysis';
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showMessage(`Failed to start analysis: ${error.message}`, 'error');
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = 'Full Analysis';
    });
}

// Replace startQuickScan function

function startQuickScan() {
    const quickScanBtn = document.getElementById('quick-scan-btn');
    const path = document.getElementById('music-directory').value;
    const recursive = document.getElementById('recursive-scan').checked;
    
    if (!path) {
        showMessage('Please enter and save a music folder path first', 'error');
        return;
    }
    
    // Show loading state
    quickScanBtn.disabled = true;
    quickScanBtn.textContent = 'Starting Scan...';
    
    // First save the path
    fetch('/api/settings/save_music_path', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            path: path,
            recursive: recursive
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Now start the quick scan in background
            return fetch('/scan_library', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    directory: path,
                    recursive: recursive
                })
            });
        } else {
            throw new Error(data.message || 'Failed to save path');
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showMessage('Quick scan started in background', 'success');
            
            // Start polling for updates
            startPollingQuickScanStatus();
            
            // Also update the global status indicator
            if (window.checkGlobalAnalysisStatus) {
                window.checkGlobalAnalysisStatus();
            }
        } else {
            showMessage(`Error: ${data.error || 'Unknown error'}`, 'error');
            quickScanBtn.disabled = false;
            quickScanBtn.textContent = 'Quick Scan';
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showMessage(`Failed to start scan: ${error.message}`, 'error');
        quickScanBtn.disabled = false;
        quickScanBtn.textContent = 'Quick Scan';
    });
}

// Add the polling function for quick scan status
function startPollingQuickScanStatus() {
    const statusContainer = document.getElementById('analysis-status');
    const quickScanBtn = document.getElementById('quick-scan-btn');
    
    function checkStatus() {
        fetch('/api/quick-scan/status')
            .then(response => response.json())
            .then(status => {
                if (status.running) {
                    // Update status display
                    let statusHtml = `
                        <div class="status-progress">
                            <p>Quick scanning files...</p>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${status.percent_complete}%"></div>
                            </div>
                            <p>${status.files_processed} files processed</p>
                        </div>
                    `;
                    
                    statusContainer.innerHTML = statusHtml;
                    
                    // Keep button disabled
                    quickScanBtn.disabled = true;
                    quickScanBtn.textContent = 'Scanning...';
                    
                    // Continue polling
                    setTimeout(checkStatus, 1000);
                } else if (status.error) {
                    // Show error
                    statusContainer.innerHTML = `
                        <div class="status-error">
                            Error: ${status.error}
                        </div>
                    `;
                    
                    // Re-enable button
                    quickScanBtn.disabled = false;
                    quickScanBtn.textContent = 'Quick Scan';
                } else if (status.files_processed > 0) {
                    // Show success
                    statusContainer.innerHTML = `
                        <div class="status-success">
                            Scan complete! Processed ${status.files_processed} files, added ${status.tracks_added} new tracks.
                        </div>
                    `;
                    
                    // Re-enable button
                    quickScanBtn.disabled = false;
                    quickScanBtn.textContent = 'Quick Scan';
                }
            })
            .catch(error => {
                console.error('Error checking quick scan status:', error);
                // Continue polling even on error
                setTimeout(checkStatus, 3000);
            });
    }
    
    // Start checking immediately
    checkStatus();
}

// Modify the updateMetadata function to trigger the global status indicator

function updateMetadata() {
    const updateBtn = document.getElementById('update-metadata-btn');
    const statusElem = document.getElementById('metadata-status-text');
    const skipExisting = document.getElementById('skip-existing-metadata').checked;
    
    // Show loading state
    updateBtn.disabled = true;
    updateBtn.textContent = 'Updating...';
    
    if (statusElem) {
        statusElem.textContent = 'Starting metadata update...';
        statusElem.parentElement.style.display = 'block';
    }
    
    fetch('/api/update-metadata', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            skip_existing: skipExisting
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showMessage('Metadata update started in background', 'success');
            
            // Start polling with minimal UI updates
            startPollingMetadataStatus();
            
            // Trigger global status check right away
            if (window.checkBackgroundTasks) {
                window.checkBackgroundTasks();
            }
        } else {
            showMessage(`Error: ${data.message || data.error || 'Unknown error'}`, 'error');
            if (statusElem) {
                statusElem.textContent = `Error: ${data.message || data.error || 'Unknown error'}`;
            }
            updateBtn.disabled = false;
            updateBtn.textContent = 'Update Metadata';
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showMessage('Failed to start metadata update', 'error');
        if (statusElem) {
            statusElem.textContent = 'Failed to start metadata update';
        }
        updateBtn.disabled = false;
        updateBtn.textContent = 'Update Metadata';
    });
}

// Modify the startPollingMetadataStatus to work with shorter polling intervals
// but only while on the settings page
function startPollingMetadataStatus() {
    const updateBtn = document.getElementById('update-metadata-btn');
    const statusElem = document.getElementById('metadata-status-text');
    
    // Create a progress bar if it doesn't exist
    let progressBar = document.getElementById('metadata-progress-bar');
    let progressFill = document.getElementById('metadata-progress-fill');
    
    if (!progressBar) {
        const statusContainer = statusElem.parentElement;
        progressBar = document.createElement('div');
        progressBar.id = 'metadata-progress-bar';
        progressBar.className = 'progress-bar';
        progressFill = document.createElement('div');
        progressFill.id = 'metadata-progress-fill';
        progressFill.className = 'progress-fill';
        progressBar.appendChild(progressFill);
        statusContainer.insertBefore(progressBar, statusElem);
    }
    
    // We'll use a shorter polling interval for the settings page since it's the focused UI
    const pollInterval = 1000; // 1 second
    let timer = null;
    
    function checkStatus() {
        fetch('/api/metadata-update/status')
            .then(response => response.json())
            .then(data => {
                // Update progress bar
                progressFill.style.width = `${data.percent_complete}%`;
                
                if (data.running) {
                    const processed = data.processed_tracks || 0;
                    const total = data.total_tracks || 0;
                    const updated = data.updated_tracks || 0;
                    
                    statusElem.textContent = `Updating metadata: ${processed}/${total} tracks (${updated} updated)`;
                    
                    // Only continue polling if we're still on the settings page
                    if (document.getElementById('update-metadata-btn')) {
                        timer = setTimeout(checkStatus, pollInterval);
                    }
                } else if (data.error) {
                    statusElem.textContent = `Error updating metadata: ${data.error}`;
                    updateBtn.disabled = false;
                    updateBtn.textContent = 'Update Metadata';
                } else if (data.processed_tracks > 0) {
                    // Update completed
                    progressFill.style.width = '100%';
                    statusElem.textContent = `Metadata update complete! ${data.updated_tracks} of ${data.total_tracks} tracks updated.`;
                    updateBtn.disabled = false;
                    updateBtn.textContent = 'Update Metadata';
                }
            })
            .catch(error => {
                console.error('Error checking metadata status:', error);
                statusElem.textContent = 'Error checking update status';
                updateBtn.disabled = false;
                updateBtn.textContent = 'Update Metadata';
            });
    }
    
    // Start checking status with initial frequency
    checkStatus();
    
    // Clean up function to stop polling
    return function stopPolling() {
        if (timer) clearTimeout(timer);
    };
}

// Update artist images
function updateArtistImages(service) {
    const updateBtn = service === 'lastfm' ? 
        document.getElementById('update-lastfm-btn') : 
        document.getElementById('update-spotify-btn');
    
    const statusElem = document.getElementById('metadata-status-text');
    
    // Show loading state
    updateBtn.disabled = true;
    updateBtn.textContent = 'Updating...';
    
    if (statusElem) {
        statusElem.textContent = `Starting artist image update via ${service}...`;
        statusElem.parentElement.style.display = 'block';
    }
    
    const endpoint = service === 'lastfm' ? 
        '/api/update-artist-images' : 
        '/api/update-artist-images/spotify';
    
    fetch(endpoint, {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showMessage(`Artist images updated via ${service}! Updated ${data.updated} of ${data.total} artists.`, 'success');
            if (statusElem) {
                statusElem.textContent = `Artist images updated via ${service}! Updated ${data.updated} of ${data.total} artists.`;
            }
        } else {
            showMessage(`Error: ${data.error || 'Unknown error'}`, 'error');
            if (statusElem) {
                statusElem.textContent = `Error: ${data.error || 'Unknown error'}`;
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showMessage(`Failed to update artist images via ${service}`, 'error');
        if (statusElem) {
            statusElem.textContent = `Failed to update artist images via ${service}`;
        }
    })
    .finally(() => {
        // Reset button
        updateBtn.disabled = false;
        updateBtn.textContent = service === 'lastfm' ? 'Update via LastFM' : 'Update via Spotify';
    });
}

// Load cache statistics
function loadCacheStats() {
    const statsElem = document.querySelector('.cache-stats');
    
    if (!statsElem) return;
    
    statsElem.innerHTML = '<div class="stats-loading">Loading cache statistics...</div>';
    
    fetch('/cache/stats')
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                let html = `
                    <div class="stat-item">
                        <div class="stat-label">Cache Directory:</div>
                        <div class="stat-value">${data.cache_directory}</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">Files Cached:</div>
                        <div class="stat-value">${data.file_count}</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">Total Size:</div>
                        <div class="stat-value">${data.total_size_mb} MB / ${data.max_size_mb} MB</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">Usage:</div>
                        <div class="stat-value">
                            <div class="cache-usage-bar">
                                <div class="cache-usage-fill" style="width: ${data.usage_percent}%"></div>
                            </div>
                            <div class="cache-usage-text">${data.usage_percent}%</div>
                        </div>
                    </div>
                `;
                statsElem.innerHTML = html;
            } else {
                statsElem.innerHTML = '<div class="error">Failed to load cache statistics</div>';
            }
        })
        .catch(error => {
            console.error('Error:', error);
            statsElem.innerHTML = '<div class="error">Error loading cache statistics</div>';
        });
}

// Clear cache
function clearCache() {
    const clearBtn = document.getElementById('clear-cache-btn');
    
    // Show loading state
    clearBtn.disabled = true;
    clearBtn.textContent = 'Clearing...';
    
    fetch('/cache/clear', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            showMessage(`Cache cleared successfully! Removed ${data.files_removed} files.`, 'success');
            loadCacheStats(); // Refresh stats
        } else {
            showMessage(`Error: ${data.message || 'Unknown error'}`, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showMessage('Failed to clear cache', 'error');
    })
    .finally(() => {
        // Reset button
        clearBtn.disabled = false;
        clearBtn.textContent = 'Clear Cache';
    });
}

// Update the analysis status with polling
function updateAnalysisStatus() {
    fetch('/api/analysis/status')
        .then(response => response.json())
        .then(status => {
            const statusContainer = document.getElementById('analysis-status');
            
            if (!statusContainer) return;
            
            if (status.running) {
                // Show progress
                const percent = status.percent_complete || 0;
                const filesProcessed = status.files_processed || 0;
                
                let statusHtml = '';
                
                if (percent < 50) {
                    // Step 1: Quick scanning
                    statusHtml = `
                        <div class="status-progress">
                            <p>Step 1/2: Quick scanning files...</p>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${percent*2}%"></div>
                            </div>
                            <p>${filesProcessed} files processed</p>
                        </div>
                    `;
                } else {
                    // Step 2: Feature analysis
                    statusHtml = `
                        <div class="status-progress">
                            <p>Step 2/2: Analyzing audio features...</p>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${(percent-50)*2}%"></div>
                            </div>
                            <p>${filesProcessed} files processed</p>
                        </div>
                    `;
                }
                
                statusContainer.innerHTML = statusHtml;
                
                // Poll again in 1 second
                setTimeout(updateAnalysisStatus, 1000);
            } else if (status.error) {
                // Show error
                statusContainer.innerHTML = `
                    <div class="status-error">
                        Error: ${status.error}
                    </div>
                `;
            } else if (status.files_processed > 0) {
                // Show success
                statusContainer.innerHTML = `
                    <div class="status-success">
                        Analysis complete! ${status.files_processed} files processed.
                    </div>
                `;
                
                // Re-enable the analyze button
                const analyzeBtn = document.getElementById('analyze-button');
                if (analyzeBtn) {
                    analyzeBtn.disabled = false;
                    analyzeBtn.textContent = 'Full Analysis';
                }
            }
        })
        .catch(error => {
            console.error('Error checking analysis status:', error);
            // Poll again in 5 seconds
            setTimeout(updateAnalysisStatus, 5000);
        });
}

// Helper function to show messages
function showMessage(message, type) {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    
    const container = document.getElementById('toast-container');
    if (container) {
        container.appendChild(toast);
        
        // Remove after 3 seconds
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => {
                container.removeChild(toast);
            }, 500);
        }, 3000);
    }
}

// Add this function to settings.js after the showMessage function

function initDatabasePerformanceSettings() {
    const form = document.querySelector('.settings-form');
    if (form) {
        form.addEventListener('submit', function(e) {
            const optimizeConnections = document.getElementById('optimize_connections').checked;
            const inMemory = document.getElementById('in_memory').checked;
            const cacheSize = document.getElementById('cache_size_mb').value;
            const formData = new FormData(form);
            formData.append('optimize_connections', optimizeConnections);
            formData.append('in_memory', inMemory);
            formData.append('cache_size_mb', cacheSize);
            // ...existing code...
        });
    }
}

// Library Statistics
function updateLibraryStats() {
    const totalTracks = document.getElementById('total-tracks');
    const tracksWithMetadata = document.getElementById('tracks-with-metadata');
    const analyzedTracks = document.getElementById('analyzed-tracks');
    const dbSize = document.getElementById('db-size');
    const cacheSize = document.getElementById('cache-size');
    
    if (!totalTracks || !tracksWithMetadata || !analyzedTracks || !dbSize || !cacheSize) {
        console.error('Library stats elements not found in DOM');
        return;
    }
    
    fetch('/api/library/stats')
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                const stats = data.stats;
                totalTracks.textContent = stats.total_tracks.toLocaleString();
                
                // Show metadata as percentage of total
                const metadataPercent = stats.total_tracks > 0 
                    ? Math.round((stats.tracks_with_metadata / stats.total_tracks) * 100) 
                    : 0;
                tracksWithMetadata.textContent = `${stats.tracks_with_metadata.toLocaleString()} (${metadataPercent}%)`;
                
                // Show analyzed as percentage of total
                const analyzedPercent = stats.total_tracks > 0 
                    ? Math.round((stats.analyzed_tracks / stats.total_tracks) * 100) 
                    : 0;
                analyzedTracks.textContent = `${stats.analyzed_tracks.toLocaleString()} (${analyzedPercent}%)`;
                
                // Show sizes in MB
                dbSize.textContent = `${stats.db_size_mb} MB`;
                cacheSize.textContent = `${stats.cache_size_mb} MB`;
            } else {
                console.error('Error fetching library stats:', data.message || 'Unknown error');
            }
        })
        .catch(error => {
            console.error('Error fetching library stats:', error);
        });
}

// Add this event listener to clear current page on unload
window.addEventListener('beforeunload', function() {
    // Let the server know we're leaving the settings page
    if (sessionStorage.getItem('currentPage') === 'settings') {
        sessionStorage.removeItem('currentPage');
        
        // Stop any active polls
        if (window.metadataPoller) {
            window.metadataPoller();
        }
    }
});

// Add a function to handle the page visibility changes
document.addEventListener('visibilitychange', function() {
    if (document.visibilityState === 'hidden') {
        // Page is hidden, slow down or pause polling
        if (window.metadataPoller) {
            window.metadataPoller();
            window.metadataPoller = null;
        }
    } else if (document.visibilityState === 'visible' && 
              sessionStorage.getItem('currentPage') === 'settings') {
        // Page is visible again, restart polling if we're on the settings page
        window.metadataPoller = startPollingMetadataStatus();
    }
});

document.getElementById('test-api-connections').addEventListener('click', function() {
    this.disabled = true;
    this.textContent = 'Testing...';
    
    fetch('/api/test-credentials')
        .then(response => response.json())
        .then(data => {
            let message = '';
            
            if (data.lastfm) {
                message += 'Last.fm: ';
                if (data.lastfm.connection) {
                    message += '✅ Connected\n';
                } else if (!data.lastfm.has_key) {
                    message += '❌ No API key configured\n';
                } else {
                    message += `❌ Connection failed (${data.lastfm.status || data.lastfm.error})\n`;
                }
            }
            
            // Similar for Spotify
            
            alert(message);
        })
        .catch(error => {
            alert('Error testing connections: ' + error);
        })
        .finally(() => {
            this.disabled = false;
            this.textContent = 'Test API Connections';
        });
});

// Update the next scheduled run display
function updateNextRunDisplay() {
    const scheduleFrequency = document.getElementById('schedule_frequency');
    const nextRunElement = document.getElementById('next-run-time');
    const nextRunContainer = document.getElementById('next-scheduled-run-info');
    
    if (scheduleFrequency && nextRunElement && nextRunContainer) {
        const frequency = scheduleFrequency.value;
        
        if (frequency === 'never') {
            nextRunElement.textContent = 'Not scheduled';
            nextRunContainer.style.display = 'none';
        } else {
            nextRunContainer.style.display = 'block';
            
            // Request updated next run time from server
            fetch('/api/next-scheduled-run')
                .then(response => response.json())
                .then(data => {
                    if (data.next_run) {
                        nextRunElement.textContent = data.next_run;
                    }
                })
                .catch(error => {
                    console.error('Error fetching next run time:', error);
                });
        }
    }
}

// Add this to your existing settings.js file

function initDatabasePerformanceSettings() {
    const checkDbStatusBtn = document.getElementById('check-db-status');
    const dbStatusDisplay = document.getElementById('db-status-display');
    
    if (checkDbStatusBtn) {
        checkDbStatusBtn.addEventListener('click', function() {
            // Show loading state
            checkDbStatusBtn.textContent = 'Loading...';
            
            // Fetch database status
            fetch('/api/db-status')
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        throw new Error(data.error);
                    }
                    
                    // Update the display
                    document.getElementById('db-size').textContent = data.db_size_mb;
                    document.getElementById('track-count').textContent = data.track_count;
                    document.getElementById('in-memory-mode').textContent = data.in_memory_mode ? 'Enabled' : 'Disabled';
                    document.getElementById('memory-usage').textContent = data.approx_memory_usage_mb;
                    
                    // Show the status display
                    dbStatusDisplay.style.display = 'block';
                    
                    // Reset button
                    checkDbStatusBtn.textContent = 'Check Database Status';
                })
                .catch(error => {
                    alert('Error checking database status: ' + error.message);
                    checkDbStatusBtn.textContent = 'Check Database Status';
                });
        });
    }
}

// Call this from your main initialization function
window.initSettingsPage = function() {
    // Existing code...
    initDatabasePerformanceSettings();
    // Existing code...
};


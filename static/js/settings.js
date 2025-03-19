// When document is ready
document.addEventListener('DOMContentLoaded', () => {
    // Initialize settings page functions
    initLibraryManagement();
    initMetadataControls();
    initCacheControls();
    
    // Create toast container if it doesn't exist
    if (!document.getElementById('toast-container')) {
        const toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        document.body.appendChild(toastContainer);
    }
    
    // Check analysis status immediately
    updateAnalysisStatus();
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
            updateMetadata();
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

function initCacheControls() {
    const clearCacheBtn = document.getElementById('clear-cache-btn');
    const refreshStatsBtn = document.getElementById('refresh-stats-btn');
    
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
    
    // Load cache stats initially
    loadCacheStats();
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

// Start quick scan
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
    quickScanBtn.textContent = 'Scanning...';
    
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
            // Now start the quick scan
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
            showMessage(`Scan complete! Found ${data.files_processed} files, added ${data.tracks_added} tracks.`, 'success');
        } else {
            showMessage(`Error: ${data.error || 'Unknown error'}`, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showMessage(`Failed to scan library: ${error.message}`, 'error');
    })
    .finally(() => {
        // Reset button
        quickScanBtn.disabled = false;
        quickScanBtn.textContent = 'Quick Scan';
    });
}

// Update metadata
function updateMetadata() {
    const updateBtn = document.getElementById('update-metadata-btn');
    const statusElem = document.getElementById('metadata-status-text');
    
    // Show loading state
    updateBtn.disabled = true;
    updateBtn.textContent = 'Updating...';
    
    if (statusElem) {
        statusElem.textContent = 'Starting metadata update...';
        statusElem.parentElement.style.display = 'block';
    }
    
    fetch('/api/update-metadata', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showMessage(`Metadata updated successfully! Updated ${data.updated} tracks.`, 'success');
            if (statusElem) {
                statusElem.textContent = `Metadata updated successfully! Updated ${data.updated} of ${data.total} tracks.`;
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
        showMessage('Failed to update metadata', 'error');
        if (statusElem) {
            statusElem.textContent = 'Failed to update metadata';
        }
    })
    .finally(() => {
        // Reset button
        updateBtn.disabled = false;
        updateBtn.textContent = 'Update Metadata';
    });
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
    const statusContainer = document.getElementById('analysis-status');
    const progressFill = document.getElementById('analysis-progress-fill');
    const statusText = document.getElementById('analysis-status-text');
    const analyzeBtn = document.getElementById('analyze-button');
    
    if (!statusContainer || !progressFill || !statusText) return;
    
    // Function to update UI with status
    function checkStatus() {
        fetch('/api/analyze/status')
            .then(response => response.json())
            .then(data => {
                // Show status container
                statusContainer.style.display = 'block';
                
                if (data.running) {
                    // Analysis is running
                    const percent = data.percent_complete || 0;
                    progressFill.style.width = `${percent}%`;
                    
                    const filesProcessed = data.files_processed || 0;
                    const totalFiles = data.total_files || 0;
                    
                    statusText.textContent = `Analyzing ${filesProcessed}/${totalFiles} files (${percent}%)`;
                    statusText.innerHTML += `<br>Current file: ${data.current_file || 'Unknown'}`;
                    
                    if (analyzeBtn) {
                        analyzeBtn.disabled = true;
                        analyzeBtn.textContent = 'Analysis Running...';
                    }
                    
                    // Continue polling while running
                    setTimeout(checkStatus, 2000);
                } else if (data.error) {
                    // Analysis finished with error
                    statusText.textContent = `Error: ${data.error}`;
                    progressFill.style.width = '0%';
                    
                    if (analyzeBtn) {
                        analyzeBtn.disabled = false;
                        analyzeBtn.textContent = 'Full Analysis';
                    }
                } else {
                    // Analysis completed or not running
                    if (data.files_processed && data.files_processed > 0) {
                        // Completed
                        progressFill.style.width = '100%';
                        statusText.textContent = `Analysis complete! Processed ${data.files_processed} files, added ${data.tracks_added || 0} tracks.`;
                    } else {
                        // Not running and no data
                        statusContainer.style.display = 'none';
                    }
                    
                    if (analyzeBtn) {
                        analyzeBtn.disabled = false;
                        analyzeBtn.textContent = 'Full Analysis';
                    }
                }
            })
            .catch(error => {
                console.error('Error getting analysis status:', error);
                statusText.textContent = 'Error getting status';
                
                if (analyzeBtn) {
                    analyzeBtn.disabled = false;
                    analyzeBtn.textContent = 'Full Analysis';
                }
            });
    }
    
    // Start checking status
    checkStatus();
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
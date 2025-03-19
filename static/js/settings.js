// Add this to your settings.js file or create if it doesn't exist

// When document is ready
document.addEventListener('DOMContentLoaded', () => {
    // Initialize settings page functions
    initLibraryManagement();
    initAnalysisManagement();
    updateAnalysisStatus();
    initCacheManagement();
    initLogSettings();
    initAPIManagement();

    // Create toast container if it doesn't exist
    if (!document.getElementById('toast-container')) {
        const toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.className = 'position-fixed top-0 end-0 p-3';
        toastContainer.style.zIndex = '1050';
        document.body.appendChild(toastContainer);
    }
});

// Helper function to show messages (if not already defined in your code)
function showMessage(message, type) {
    // Check if you already have a message display function
    if (window.showMessage) {
        window.showMessage(message, type);
        return;
    }
    
    // Create a simple message display if none exists
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;
    messageDiv.textContent = message;
    
    const container = document.querySelector('.settings-form') || document.body;
    container.prepend(messageDiv);
    
    // Remove after 3 seconds
    setTimeout(() => {
        messageDiv.remove();
    }, 3000);
}

function initLibraryManagement() {
    const musicDirInput = document.getElementById('music-directory');
    const recursiveCheckbox = document.getElementById('recursive-scan');
    const savePathBtn = document.getElementById('save-music-path');
    const scanLibraryBtn = document.getElementById('scan-library-btn');
    
    if (savePathBtn) {
        savePathBtn.addEventListener('click', async () => {
            const musicDir = musicDirInput.value;
            if (!musicDir) {
                showToast('Please specify a music directory', 'error');
                return;
            }
            
            try {
                const response = await fetch('/api/settings/save_music_path', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        path: musicDir,
                        recursive: recursiveCheckbox.checked
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showToast('Music folder path saved successfully', 'success');
                } else {
                    showToast(`Error: ${data.message}`, 'error');
                }
            } catch (error) {
                showToast(`Failed to save path: ${error}`, 'error');
            }
        });
    }
    
    if (scanLibraryBtn) {
        scanLibraryBtn.addEventListener('click', async () => {
            const musicDir = musicDirInput.value;
            if (!musicDir) {
                showToast('Please specify a music directory', 'error');
                return;
            }
            
            const originalText = scanLibraryBtn.innerHTML;
            scanLibraryBtn.disabled = true;
            scanLibraryBtn.textContent = 'Scanning...';
            
            try {
                const response = await fetch('/scan_library', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        directory: musicDir,
                        recursive: recursiveCheckbox.checked
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showToast(`Library scan complete! Found ${data.tracks_added} new tracks.`, 'success');
                    updateAnalysisStatus();
                } else {
                    showToast(`Error: ${data.message}`, 'error');
                }
            } catch (error) {
                showToast(`Failed to scan library: ${error}`, 'error');
            } finally {
                scanLibraryBtn.disabled = false;
                scanLibraryBtn.textContent = 'Quick Scan Library';
            }
        });
    }
    
    // Update metadata button
    const updateMetadataBtn = document.getElementById('update-metadata-btn');
    if (updateMetadataBtn) {
        updateMetadataBtn.addEventListener('click', async () => {
            updateMetadataBtn.disabled = true;
            updateMetadataBtn.textContent = 'Updating...';
            
            try {
                const response = await fetch('/api/update-metadata', {
                    method: 'POST'
                });
                
                const data = await response.json();
                
                if (data.error) {
                    showToast(`Error: ${data.error}`, 'error');
                } else {
                    showToast(`Updated metadata for ${data.updated} tracks. Updated ${data.images_updated} images.`, 'success');
                }
            } catch (error) {
                showToast(`Failed to update metadata: ${error}`, 'error');
            } finally {
                updateMetadataBtn.disabled = false;
                updateMetadataBtn.textContent = 'Update Metadata';
            }
        });
    }
}

function initAnalysisManagement() {
    const startAnalysisBtn = document.getElementById('start-analysis-btn');
    const stopAnalysisBtn = document.getElementById('stop-analysis-btn');
    const progressSection = document.getElementById('analysis-progress');
    
    if (startAnalysisBtn) {
        startAnalysisBtn.addEventListener('click', async () => {
            startAnalysisBtn.disabled = true;
            if (progressSection) progressSection.classList.remove('hidden');
            
            try {
                const response = await fetch('/start_background_analysis', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        batch_size: 10,
                    })
                });
                
                const data = await response.json();
                
                if (data.status === 'started') {
                    startProgressPolling();
                    showToast('Background analysis started!', 'success');
                } else if (data.status === 'already_running') {
                    showToast('Analysis is already running', 'info');
                } else {
                    showToast(`Failed to start analysis: ${data.message}`, 'error');
                    startAnalysisBtn.disabled = false;
                    if (progressSection) progressSection.classList.add('hidden');
                }
            } catch (error) {
                showToast(`Error: ${error}`, 'error');
                startAnalysisBtn.disabled = false;
                if (progressSection) progressSection.classList.add('hidden');
            }
        });
    }
    
    if (stopAnalysisBtn) {
        stopAnalysisBtn.addEventListener('click', async () => {
            try {
                const response = await fetch('/stop_background_analysis', {
                    method: 'POST'
                });
                
                const data = await response.json();
                
                if (data.status === 'stopped') {
                    showToast('Analysis stopped', 'info');
                    stopProgressPolling();
                    if (startAnalysisBtn) startAnalysisBtn.disabled = false;
                    if (progressSection) progressSection.classList.add('hidden');
                }
            } catch (error) {
                showToast(`Error stopping analysis: ${error}`, 'error');
            }
        });
    }
}

let progressPollInterval;

function startProgressPolling() {
    progressPollInterval = setInterval(updateAnalysisProgress, 2000);
    updateAnalysisProgress(); // Immediate first update
}

function stopProgressPolling() {
    if (progressPollInterval) {
        clearInterval(progressPollInterval);
    }
}

async function updateAnalysisProgress() {
    try {
        const response = await fetch('/analysis_progress');
        const data = await response.json();
        
        const progressBar = document.getElementById('analysis-progress-bar');
        const statusText = document.getElementById('analysis-status-text');
        
        if (data.is_running) {
            // Update progress UI
            const progress = Math.round(data.progress * 100);
            
            if (progressBar) {
                progressBar.style.width = `${progress}%`;
                progressBar.textContent = `${progress}%`;
            }
            
            if (statusText) {
                statusText.textContent = `Analyzing files... ${data.current_file_index}/${data.total_files}`;
            }
            
            // Update status counts
            updateElementText('pending-count', data.pending_count);
            updateElementText('analyzed-count', data.analyzed_count);
            updateElementText('failed-count', data.failed_count);
        } else {
            // Analysis finished or not running
            stopProgressPolling();
            const startBtn = document.getElementById('start-analysis-btn');
            if (startBtn) startBtn.disabled = false;
            
            const progressSection = document.getElementById('analysis-progress');
            if (progressSection) progressSection.classList.add('hidden');
            
            if (data.last_run_completed) {
                showToast('Analysis complete!', 'success');
            }
            
            // Update status counts one final time
            updateAnalysisStatus();
        }
    } catch (error) {
        console.error('Error fetching analysis progress:', error);
    }
}

function updateElementText(id, text) {
    const element = document.getElementById(id);
    if (element) {
        element.textContent = text;
    }
}

async function updateAnalysisStatus() {
    try {
        const response = await fetch('/analysis_status');
        const data = await response.json();
        
        updateElementText('pending-count', data.pending);
        updateElementText('analyzed-count', data.analyzed);
        updateElementText('failed-count', data.failed);
    } catch (error) {
        console.error('Error fetching analysis status:', error);
    }
}

function initCacheManagement() {
    // Your existing cache management code
    // ...
}

function initLogSettings() {
    // Your existing log settings code
    // ...
}

function initAPIManagement() {
    // Your existing API management code
    // ...
}

function showToast(message, type = 'info') {
    // Check if toast container exists, if not create it
    let toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.className = 'position-fixed top-0 end-0 p-3';
        toastContainer.style.zIndex = '1050';
        document.body.appendChild(toastContainer);
    }
    
    // Create toast element
    const toastId = 'toast-' + Date.now();
    const toast = document.createElement('div');
    toast.id = toastId;
    toast.className = `toast ${type === 'error' ? 'bg-danger text-white' : 
                         type === 'success' ? 'bg-success text-white' : 
                         type === 'warning' ? 'bg-warning' : 'bg-info text-white'}`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    
    toast.innerHTML = `
        <div class="toast-header">
            <strong class="me-auto">${type.charAt(0).toUpperCase() + type.slice(1)}</strong>
            <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
        <div class="toast-body">
            ${message}
        </div>
    `;
    
    toastContainer.appendChild(toast);
    
    // Initialize and show the toast using vanilla JS if Bootstrap isn't available
    try {
        // Try to use Bootstrap Toast if available
        if (window.bootstrap && bootstrap.Toast) {
            const bsToast = new bootstrap.Toast(toast, { delay: 5000 });
            bsToast.show();
        } else {
            // Fallback to basic functionality
            toast.style.display = 'block';
            setTimeout(() => {
                toast.style.opacity = '0';
                setTimeout(() => toast.remove(), 500);
            }, 5000);
            
            // Add manual close button functionality
            const closeBtn = toast.querySelector('.btn-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => {
                    toast.style.opacity = '0';
                    setTimeout(() => toast.remove(), 500);
                });
            }
        }
    } catch (e) {
        console.error('Toast error:', e);
        // Extra fallback
        toast.style.display = 'block';
        setTimeout(() => toast.remove(), 5000);
    }
}
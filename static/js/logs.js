document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing logs page functionality');
    
    // Get DOM elements
    const logContent = document.getElementById('log-content');
    const logLines = document.getElementById('log-lines');
    const refreshBtn = document.getElementById('refresh-logs');
    const downloadBtn = document.getElementById('download-logs');
    
    // Check if we're on the logs page
    if (!logContent || !logLines || !refreshBtn) {
        console.log('Not on logs page or missing required elements');
        return;
    }
    
    console.log('Found log page elements, setting up functionality');
    
    // Initialize by loading logs
    loadLogs();
    
    // Set up event listeners
    refreshBtn.addEventListener('click', loadLogs);
    logLines.addEventListener('change', loadLogs);
    
    if (downloadBtn) {
        downloadBtn.addEventListener('click', function() {
            window.location.href = '/api/logs/download';
        });
    }
    
    function loadLogs() {
        const lines = logLines.value;
        logContent.innerHTML = '<div class="loading">Loading logs...</div>';
        
        console.log('Loading logs with', lines, 'lines');
        
        fetch(`/api/logs/view?lines=${lines}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    logContent.innerHTML = `<div class="error">${data.error}</div>`;
                    return;
                }
                
                if (!data.logs || data.logs.length === 0) {
                    logContent.innerHTML = '<div class="empty">No logs found</div>';
                    return;
                }
                
                logContent.innerHTML = '';
                data.logs.forEach(line => {
                    const logLine = document.createElement('div');
                    logLine.className = 'log-line';
                    logLine.textContent = line;
                    
                    // Add color based on log level
                    if (line.includes(' DEBUG ')) logLine.classList.add('log-debug');
                    if (line.includes(' INFO ')) logLine.classList.add('log-info');
                    if (line.includes(' WARNING ')) logLine.classList.add('log-warning');
                    if (line.includes(' ERROR ')) logLine.classList.add('log-error');
                    if (line.includes(' CRITICAL ')) logLine.classList.add('log-critical');
                    
                    logContent.appendChild(logLine);
                });
                
                // Scroll to bottom
                logContent.scrollTop = logContent.scrollHeight;
            })
            .catch(error => {
                console.error('Error loading logs:', error);
                logContent.innerHTML = `<div class="error">Error loading logs: ${error.message}</div>`;
            });
    }
    
    // Flag that we've initialized
    window.logsInitialized = true;
});
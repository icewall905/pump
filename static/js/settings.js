// Add this to your settings.js file or create if it doesn't exist

// When document is ready
document.addEventListener('DOMContentLoaded', function() {
    // Load current log level
    fetch('/api/settings/get_log_level')
        .then(response => response.json())
        .then(data => {
            if (data.level) {
                document.getElementById('log-level').value = data.level;
            }
        })
        .catch(error => {
            console.error('Error loading log level:', error);
        });

    // Handle saving log level
    document.getElementById('save-log-level').addEventListener('click', function() {
        const level = document.getElementById('log-level').value;
        
        fetch('/api/settings/change_log_level', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ level: level })
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                showMessage(data.error, 'error');
            } else {
                showMessage('Log level updated successfully', 'success');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showMessage('Failed to update log level', 'error');
        });
    });
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
document.addEventListener('DOMContentLoaded', function() {
    // Navigation links
    const exploreLink = document.getElementById('explore-link');
    const recentLink = document.getElementById('recent-link');
    
    if (exploreLink) {
        exploreLink.addEventListener('click', function(e) {
            e.preventDefault();
            window.location.href = '/?view=explore';
        });
    }
    
    if (recentLink) {
        recentLink.addEventListener('click', function(e) {
            e.preventDefault();
            window.location.href = '/?view=recent';
        });
    }
});
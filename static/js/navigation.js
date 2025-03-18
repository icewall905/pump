document.addEventListener('DOMContentLoaded', function() {
    // Navigation links
    const homeLink = document.getElementById('home-link');
    const exploreLink = document.getElementById('explore-link');
    const recentLink = document.getElementById('recent-link');
    const libraryLink = document.getElementById('library-link');
    const settingsLink = document.getElementById('settings-link');
    
    // Set all links to navigate via full page reload
    if (homeLink) {
        homeLink.addEventListener('click', function(e) {
            e.preventDefault();
            // Remove all active classes
            document.querySelectorAll('.sidebar-nav a').forEach(
                link => link.classList.remove('active'));
            // Add active to clicked link
            homeLink.classList.add('active');
            window.location.href = '/?view=home';
        });
    }
    
    if (exploreLink) {
        exploreLink.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelectorAll('.sidebar-nav a').forEach(
                link => link.classList.remove('active'));
            exploreLink.classList.add('active');
            window.location.href = '/?view=explore';
        });
    }
    
    if (recentLink) {
        recentLink.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelectorAll('.sidebar-nav a').forEach(
                link => link.classList.remove('active'));
            recentLink.classList.add('active');
            window.location.href = '/?view=recent';
        });
    }
});
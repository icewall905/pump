// Add this in your existing document.addEventListener('DOMContentLoaded', function(){}) block

// Library link
const libraryLink = document.getElementById('library-link');
if (libraryLink) {
    libraryLink.addEventListener('click', function(e) {
        e.preventDefault();
        window.location.href = '/library';
    });
}
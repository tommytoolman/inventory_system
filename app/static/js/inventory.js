// static/js/inventory.js
document.addEventListener('DOMContentLoaded', function() {
    // Get all select elements
    const selects = document.querySelectorAll('select');
    
    selects.forEach(select => {
        select.addEventListener('keypress', (e) => {
            // Get all options except the first one (which is "All Categories/Brands")
            const options = Array.from(select.options).slice(1);
            
            // Find first option that starts with pressed key
            const firstMatch = options.find(option => 
                option.text.toLowerCase().startsWith(e.key.toLowerCase())
            );
            
            if (firstMatch) {
                select.value = firstMatch.value;
                // Optionally, submit the form automatically
                // select.form.submit();
            }
        });
    });
});
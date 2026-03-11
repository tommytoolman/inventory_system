// static/js/inventory.js - Enhanced inventory list functionality

// Existing keyboard navigation functionality
document.addEventListener('DOMContentLoaded', function() {
    // Get all select elements for keyboard navigation
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
                // Trigger change event for the new filtering system
                select.dispatchEvent(new Event('change'));
            }
        });
    });
});

// Modern inventory list with instant filtering and sorting
class InventoryList {
    constructor(config) {
        this.currentPage = config.currentPage;
        this.perPage = config.perPage;
        this.currentSort = { column: null, direction: 'asc' };
        this.debounceTimeout = null;
        
        this.initializeEventListeners();
        
        // Initialize visual cues on load - ADD THIS
        setTimeout(() => this.updateFilterVisualCues(), 100);
    }
    
    initializeEventListeners() {
        // Search input with debounce
        const searchInput = document.getElementById('searchInput');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.debounceFilter(() => {
                    this.updateFilters();
                    this.updateFilterVisualCues(); // ADD THIS
                });
            });
        }
        
        // Filter dropdowns - instant change
        ['categorySelect', 'brandSelect', 'platformSelect', 'statusSelect'].forEach(id => {
            const element = document.getElementById(id);
            if (element) {
                element.addEventListener('change', () => {
                    this.updateFilters();
                    this.updateFilterVisualCues(); // ADD THIS
                });
            }
        });
        
        // Per page selector
        const perPageSelect = document.getElementById('perPageSelect');
        if (perPageSelect) {
            perPageSelect.addEventListener('change', (e) => {
                this.perPage = e.target.value;
                this.currentPage = 1; // Reset to first page
                this.updateFilters();
                this.updateFilterVisualCues(); // ADD THIS
            });
        }
        
        // Clear filters button
        const clearFilters = document.getElementById('clearFilters');
        if (clearFilters) {
            clearFilters.addEventListener('click', () => {
                this.clearAllFilters();
            });
        }
        
        // Sortable headers
        document.querySelectorAll('.sortable-header').forEach(header => {
            header.addEventListener('click', () => {
                const column = header.dataset.sort;
                this.toggleSort(column);
            });
        });
        
        // Initial pagination listeners
        this.initializePaginationListeners();
    }
    
    debounceFilter(func, delay = 300) {
        clearTimeout(this.debounceTimeout);
        this.debounceTimeout = setTimeout(func, delay);
    }
    
    updateFilters() {
        this.currentPage = 1; // Reset to first page when filtering
        this.loadProducts();
    }
    
    getCurrentFilterState() {
        const urlParams = new URLSearchParams(window.location.search);
        
        return {
            search: urlParams.get('search') || '',
            category: urlParams.get('category') || '',
            brand: urlParams.get('brand') || '',
            platform: urlParams.get('platform') || '',
            status: urlParams.get('status') || ''
        };
    }
    
    // Update the visual cues method to use URL state
    updateFilterVisualCues() {
        const currentState = this.getCurrentFilterState();
        
        const filters = [
            { id: 'searchInput', value: currentState.search },
            { id: 'categorySelect', value: currentState.category },
            { id: 'brandSelect', value: currentState.brand },
            { id: 'platformSelect', value: currentState.platform },
            { id: 'statusSelect', value: currentState.status }
        ];
        
        filters.forEach(filter => {
            const element = document.getElementById(filter.id);
            if (element) {
                const hasActiveFilter = filter.value && filter.value !== '';
                
                if (hasActiveFilter) {
                    element.classList.add('filter-active');
                } else {
                    element.classList.remove('filter-active');
                }
            }
        });
    }

    clearAllFilters() {
        const searchInput = document.getElementById('searchInput');
        const categorySelect = document.getElementById('categorySelect');
        const brandSelect = document.getElementById('brandSelect');
        const platformSelect = document.getElementById('platformSelect');
        const statusSelect = document.getElementById('statusSelect');
        
        if (searchInput) searchInput.value = '';
        if (categorySelect) categorySelect.value = '';
        if (brandSelect) brandSelect.value = '';
        if (platformSelect) platformSelect.value = '';
        if (statusSelect) statusSelect.value = '';
        
        this.currentSort = { column: null, direction: 'asc' };
        this.updateSortIcons();
        this.updateFilters();
        this.updateFilterVisualCues(); // ADD THIS
    }
    
    toggleSort(column) {
        if (this.currentSort.column === column) {
            this.currentSort.direction = this.currentSort.direction === 'asc' ? 'desc' : 'asc';
        } else {
            this.currentSort.column = column;
            this.currentSort.direction = 'asc';
        }
        
        this.updateSortIcons();
        this.loadProducts();
    }
    
    updateSortIcons() {
        // Reset all sort icons
        document.querySelectorAll('.sortable-header').forEach(header => {
            header.classList.remove('sort-asc', 'sort-desc');
        });
        
        // Set active sort icon
        if (this.currentSort.column) {
            const activeHeader = document.querySelector(`[data-sort="${this.currentSort.column}"]`);
            if (activeHeader) {
                activeHeader.classList.add(`sort-${this.currentSort.direction}`);
            }
        }
    }
    
    goToPage(page) {
        this.currentPage = page;
        this.loadProducts();
    }
    
    buildUrl() {
        const params = new URLSearchParams();
        
        params.set('page', this.currentPage);
        params.set('per_page', this.perPage);
        
        const searchInput = document.getElementById('searchInput');
        const search = searchInput ? searchInput.value : '';
        if (search) params.set('search', search);
        
        const categorySelect = document.getElementById('categorySelect');
        const category = categorySelect ? categorySelect.value : '';
        if (category) params.set('category', category);
        
        const brandSelect = document.getElementById('brandSelect');
        const brand = brandSelect ? brandSelect.value : '';
        if (brand) params.set('brand', brand);
        
        const platformSelect = document.getElementById('platformSelect');
        const platform = platformSelect ? platformSelect.value : '';
        if (platform) params.set('platform', platform);
        
        const statusSelect = document.getElementById('statusSelect');
        const status = statusSelect ? statusSelect.value : '';
        if (status) params.set('status', status);
        
        if (this.currentSort.column) {
            params.set('sort', this.currentSort.column);
            params.set('order', this.currentSort.direction);
        }
        
        return `/inventory/?${params.toString()}`;
    }
    
    async loadProducts() {
        try {
            // Show loading state
            document.body.classList.add('loading');
            
            const url = this.buildUrl();
            
            // Update browser URL without page reload
            window.history.pushState({}, '', url);
            
            // Fetch new data
            const response = await fetch(url, {
                headers: {
                    'Accept': 'text/html',
                }
            });
            
            if (!response.ok) {
                throw new Error('Failed to load products');
            }
            
            // Replace page content
            const html = await response.text();
            const parser = new DOMParser();
            const newDoc = parser.parseFromString(html, 'text/html');
            
            // Update table body
            const newTableBody = newDoc.getElementById('productsTableBody');
            const currentTableBody = document.getElementById('productsTableBody');
            if (newTableBody && currentTableBody) {
                currentTableBody.innerHTML = newTableBody.innerHTML;
            }
            
            // Update pagination
            const newPagination = newDoc.querySelector('.mt-6.bg-white.px-6.py-3.rounded-lg.shadow');
            const currentPagination = document.querySelector('.mt-6.bg-white.px-6.py-3.rounded-lg.shadow');
            if (newPagination && currentPagination) {
                currentPagination.innerHTML = newPagination.innerHTML;
            }
            
            // Update results count
            const newResultsCount = newDoc.getElementById('resultsCount');
            const currentResultsCount = document.getElementById('resultsCount');
            if (newResultsCount && currentResultsCount) {
                currentResultsCount.innerHTML = newResultsCount.innerHTML;
            }
            
            // Re-initialize pagination event listeners
            this.initializePaginationListeners();
            
        } catch (error) {
            console.error('Error loading products:', error);
            alert('Error loading products. Please try again.');
        } finally {
            // Remove loading state
            document.body.classList.remove('loading');
        }
    }
    
    initializePaginationListeners() {
        document.querySelectorAll('.pagination-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const page = parseInt(link.dataset.page);
                if (!isNaN(page)) {
                    this.goToPage(page);
                }
            });
        });
    }
}

// Make it available globally
window.InventoryList = InventoryList;
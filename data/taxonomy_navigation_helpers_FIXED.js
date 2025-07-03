
// FIXED JavaScript helpers for cascading dropdown implementation

class TaxonomyNavigator {
    constructor(hierarchyTreeData) {
        this.tree = hierarchyTreeData;
        this.lookup = hierarchyTreeData.lookup;
        this.selectedPath = [];
    }
    
    // Get root categories for first dropdown
    getRootCategories() {
        return this.tree.roots.map(root => ({
            id: root.id,
            name: root.name,
            fullName: root.fullName,
            hasChildren: root.children.length > 0,
            childrenCount: root.children.length
        }));
    }
    
    // Get children of a specific category for next dropdown level
    getChildren(categoryId) {
        const category = this.findCategoryInTree(categoryId);
        if (category && category.children) {
            return category.children.map(child => ({
                id: child.id,
                name: child.name,
                fullName: child.fullName,
                level: child.level,
                isLeaf: child.isLeaf,
                hasChildren: child.children.length > 0,
                childrenCount: child.children.length
            }));
        }
        return [];
    }
    
    // Find a category node in the tree structure
    findCategoryInTree(categoryId, node = null) {
        if (!node) {
            // Search all roots
            for (const root of this.tree.roots) {
                const found = this.findCategoryInTree(categoryId, root);
                if (found) return found;
            }
            return null;
        }
        
        if (node.id === categoryId) {
            return node;
        }
        
        for (const child of node.children || []) {
            const found = this.findCategoryInTree(categoryId, child);
            if (found) return found;
        }
        
        return null;
    }
    
    // Check if a category is a leaf node (can be selected)
    isLeafCategory(categoryId) {
        const category = this.findCategoryInTree(categoryId);
        return category ? category.isLeaf : false;
    }
    
    // Get the full path to a category
    getPathToCategory(categoryId) {
        const path = [];
        let currentId = categoryId;
        
        while (currentId && this.lookup[currentId]) {
            const category = this.lookup[currentId];
            path.unshift({
                id: category.id,
                name: category.name,
                level: category.level
            });
            currentId = category.parentId;
        }
        
        return path;
    }
    
    // Get user-friendly category path string
    getCategoryPath(categoryId) {
        const path = this.getPathToCategory(categoryId);
        return path.map(p => p.name).join(' > ');
    }
    
    // BONUS: Get all leaf nodes under a category (for advanced use)
    getAllLeafNodes(categoryId = null) {
        const leafNodes = [];
        
        const collectLeaves = (node) => {
            if (node.isLeaf) {
                leafNodes.push({
                    id: node.id,
                    name: node.name,
                    fullName: node.fullName,
                    level: node.level
                });
            } else {
                for (const child of node.children || []) {
                    collectLeaves(child);
                }
            }
        };
        
        if (categoryId) {
            const startNode = this.findCategoryInTree(categoryId);
            if (startNode) collectLeaves(startNode);
        } else {
            for (const root of this.tree.roots) {
                collectLeaves(root);
            }
        }
        
        return leafNodes;
    }
}

// Example usage in React/Vue/vanilla JS:
/*
// Load the hierarchy tree data
fetch('/data/musical_instruments_hierarchy_tree_fixed.json')
    .then(response => response.json())
    .then(hierarchyTreeData => {
        const navigator = new TaxonomyNavigator(hierarchyTreeData);
        
        // Level 1 dropdown - Root categories
        const rootCategories = navigator.getRootCategories();
        populateDropdown('category-level-1', rootCategories);
        
        // When user selects "Musical Instruments"
        document.getElementById('category-level-1').addEventListener('change', (e) => {
            const selectedId = e.target.value;
            const children = navigator.getChildren(selectedId);
            populateDropdown('category-level-2', children);
            clearDropdowns(['category-level-3', 'category-level-4']); // Clear subsequent levels
        });
        
        // When user selects "String Instruments"
        document.getElementById('category-level-2').addEventListener('change', (e) => {
            const selectedId = e.target.value;
            const children = navigator.getChildren(selectedId);
            populateDropdown('category-level-3', children);
            clearDropdowns(['category-level-4']); // Clear subsequent levels
        });
        
        // When user selects "Guitars"
        document.getElementById('category-level-3').addEventListener('change', (e) => {
            const selectedId = e.target.value;
            const children = navigator.getChildren(selectedId);
            populateDropdown('category-level-4', children);
        });
        
        // Final selection - "Electric Guitars" (leaf node)
        document.getElementById('category-level-4').addEventListener('change', (e) => {
            const selectedId = e.target.value;
            const isLeaf = navigator.isLeafCategory(selectedId);
            
            if (isLeaf) {
                const fullPath = navigator.getCategoryPath(selectedId);
                console.log('Final category selected:', fullPath);
                console.log('Category GID:', selectedId);
                // Now you can save this GID to your product
            }
        });
        
        function populateDropdown(dropdownId, options) {
            const dropdown = document.getElementById(dropdownId);
            dropdown.innerHTML = '<option value="">Select...</option>';
            
            options.forEach(option => {
                const optionElement = document.createElement('option');
                optionElement.value = option.id;
                optionElement.textContent = option.name;
                if (!option.isLeaf) {
                    optionElement.textContent += ` (${option.childrenCount} subcategories)`;
                }
                dropdown.appendChild(optionElement);
            });
            
            dropdown.style.display = 'block';
        }
        
        function clearDropdowns(dropdownIds) {
            dropdownIds.forEach(id => {
                const dropdown = document.getElementById(id);
                dropdown.innerHTML = '<option value="">Select...</option>';
                dropdown.style.display = 'none';
            });
        }
    });
*/

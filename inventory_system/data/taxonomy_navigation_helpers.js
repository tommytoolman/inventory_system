
// JavaScript helper functions for cascading dropdown implementation

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
            hasChildren: root.children.length > 0
        }));
    }
    
    // Get children of a specific category for next dropdown level
    getChildren(categoryId) {
        // Search in the lookup first
        if (this.lookup[categoryId] && !this.lookup[categoryId].isLeaf) {
            // Find the category in the tree and return its children
            return this.findCategoryInTree(categoryId)?.children || [];
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
        return this.lookup[categoryId]?.isLeaf || false;
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
}

// Example usage in a React/Vue component:
/*
const navigator = new TaxonomyNavigator(hierarchyTreeData);

// Level 1 dropdown
const rootCategories = navigator.getRootCategories();

// User selects "Musical Instruments"
const level2Categories = navigator.getChildren("gid://shopify/TaxonomyCategory/ae-2-8");

// User selects "String Instruments" 
const level3Categories = navigator.getChildren("gid://shopify/TaxonomyCategory/ae-2-8-7");

// User selects "Guitars"
const level4Categories = navigator.getChildren("gid://shopify/TaxonomyCategory/ae-2-8-7-2");

// User selects "Electric Guitars" - this is a leaf node
const isLeaf = navigator.isLeafCategory("gid://shopify/TaxonomyCategory/ae-2-8-7-2-4");
// isLeaf = true, so this can be the final selection

// Get the full path for display
const fullPath = navigator.getCategoryPath("gid://shopify/TaxonomyCategory/ae-2-8-7-2-4");
// "Musical Instruments > String Instruments > Guitars > Electric Guitars"
*/

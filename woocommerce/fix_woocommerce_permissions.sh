#!/bin/bash
# WooCommerce User Permissions Fixer
# This script checks and fixes user capabilities for WooCommerce API access

echo "============================================================"
echo "  WooCommerce User Permissions Fixer"
echo "============================================================"
echo ""
echo "Accessing WordPress container..."
echo ""

# Access the WordPress container and run WP-CLI commands
docker exec -it woocommerce_site bash << 'EOF'

# Install WP-CLI if not present
if ! command -v wp &> /dev/null; then
    echo "Installing WP-CLI..."
    curl -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
    chmod +x wp-cli.phar
    mv wp-cli.phar /usr/local/bin/wp
fi

echo "============================================================"
echo "Current WordPress Users:"
echo "============================================================"
wp user list --allow-root

echo ""
echo "============================================================"
echo "Checking 'harry' user role and capabilities:"
echo "============================================================"
wp user get harry --field=roles --allow-root

echo ""
echo "============================================================"
echo "Granting WooCommerce capabilities to 'harry'..."
echo "============================================================"

# Get harry's user ID
USER_ID=$(wp user get harry --field=ID --allow-root)
echo "User ID: $USER_ID"

# Make sure harry is an administrator
wp user set-role $USER_ID administrator --allow-root
echo "✅ Set role to Administrator"

# Grant specific WooCommerce capabilities
wp cap add $USER_ID manage_woocommerce --allow-root
echo "✅ Added manage_woocommerce"

wp cap add $USER_ID view_woocommerce_reports --allow-root
echo "✅ Added view_woocommerce_reports"

wp cap add $USER_ID edit_shop_orders --allow-root
echo "✅ Added edit_shop_orders"

wp cap add $USER_ID read_shop_orders --allow-root
echo "✅ Added read_shop_orders"

wp cap add $USER_ID edit_shop_coupons --allow-root
echo "✅ Added edit_shop_coupons"

wp cap add $USER_ID read_shop_coupons --allow-root
echo "✅ Added read_shop_coupons"

wp cap add $USER_ID edit_products --allow-root
echo "✅ Added edit_products"

wp cap add $USER_ID read_products --allow-root
echo "✅ Added read_products"

echo ""
echo "============================================================"
echo "Verifying 'harry' capabilities:"
echo "============================================================"
wp user list --field=user_login,roles --allow-root | grep harry

echo ""
echo "✅ Done! User 'harry' now has all WooCommerce capabilities."
echo ""
echo "Next steps:"
echo "1. The existing API key should now work"
echo "2. Run: python debug_woocommerce.py"
echo "3. You should see ✅ SUCCESS!"
echo ""

EOF

echo "============================================================"
echo "Script complete!"
echo "============================================================"
echo ""
echo "Now test your API connection:"
echo "  python debug_woocommerce.py"
echo ""
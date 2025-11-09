# app.services.shopify.client

import os
import json
import logging
import httpx
import time
import math
import asyncio
import requests
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timezone

from app.core.exceptions import ReverbAPIError
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ShopifyGraphQLError(Exception):
    """Custom exception for GraphQL errors."""
    def __init__(self, errors):
        self.errors = errors
        message = "GraphQL query failed with errors:\n"
        for error in errors:
            msg = error.get('message', 'Unknown error')
            path = error.get('path', [])
            message += f"- Message: {msg}, Path: {path}\n"
        super().__init__(message)


class ShopifyGraphQLClient:
    
    """
    Uses a hybrid GraphQL + REST approach, is the BEST strategy for Shopify.

    17 methods total 🎯:
    - 8 GraphQL methods (reads + product operations)
    - 3 REST methods (variant operations)
    - 6 infrastructure methods (rate limiting, etc.)
    
    Best of both worlds - GraphQL's power for complex operations and REST's reliability for variant management.
    Hybrid approach is how most production Shopify integrations work and exactly what Shopify experts recommend! 🚀

    Your Hybrid Architecture Breakdown:
    ✅ GraphQL for:
      # READ operations:
      - get_products_count()
      - get_all_products_summary()
      - get_product_snapshot_by_id()
      - get_shop_locations()
      - get_online_store_publication_id()

      # PRODUCT-level operations
      - create_product()
      - update_product()
      - delete_product()

      # MEDIA operations  
      - create_product_images()
      - publish_product_to_sales_channel()
  
    ✅ REST for (Only Reliable Method):
    # VARIANT-level operations
    - update_variant_rest()
    - _update_inventory_rest()
    - get_variant_details_rest()
  
  Why This Hybrid Approach is Perfect:
    
    GraphQL Strengths:
    - Rich data fetching - Get exactly what you need
    - Product management - Creating, updating product info
    - Media handling - Images, publishing
    - Relationship data - Product → variants → inventory in one query
    
    REST API Strengths:
    - Variant operations - More reliable for price/SKU/inventory updates
    - Legacy compatibility - Some variant fields only work via REST
    - Simpler debugging - Easier to troubleshoot variant issues

    Summary:
    - Use GraphQL for complex reads and product-level writes
    - Use REST for variant-level operations and inventory management

    """
    
    
    # --- Meta/Infrastructure ---
    
    def __init__(self, safety_buffer_percentage=0.25): # e.g., try to keep 25% of max available as buffer
        # --- Configuration from .env file ---
        settings = get_settings()
        self.store_domain = settings.SHOPIFY_SHOP_URL
        self.admin_api_token = settings.SHOPIFY_ADMIN_API_ACCESS_TOKEN
        self.api_version = settings.SHOPIFY_API_VERSION
        

        if not self.store_domain or not self.admin_api_token:
            raise ValueError(
                "SHOPIFY_STORE_DOMAIN and ADMIN_API_ACCESS_TOKEN must be set in .env or as environment variables."
            )

        self.graphql_url = f"https://{self.store_domain}/admin/api/{self.api_version}/graphql.json"
        self.headers = {
            "X-Shopify-Access-Token": self.admin_api_token,
            "Content-Type": "application/json"
        }

        # Initialize throttle status - will be updated after the first call
        self.max_available_points = 2000.0 # Default for Plus, 1000 for standard (will update)
        self.currently_available_points = self.max_available_points 
        self.restore_rate = 100.0 # Default (will update)
        self.safety_buffer_points = self.max_available_points * safety_buffer_percentage
        
        # print(f"ShopifyGraphQLClient initialized for {self.store_domain}")
        print(f"ShopifyGraphQLClient initialized for {self.store_domain} (Effective API Version: {self.api_version})") # Make sure this prints
        print(f"Initial safety buffer points: {self.safety_buffer_points}")

    def execute(self, query: str, variables: dict | None = None, estimated_cost: int = 10):
        return self._make_request(query, variables, estimated_cost)

    def _update_throttle_status(self, extensions):
        if extensions and "cost" in extensions:
            cost_data = extensions["cost"]
            self.max_available_points = float(cost_data["throttleStatus"]["maximumAvailable"])
            self.currently_available_points = float(cost_data["throttleStatus"]["currentlyAvailable"])
            self.restore_rate = float(cost_data["throttleStatus"]["restoreRate"])
            # Recalculate safety buffer based on actual max points
            self.safety_buffer_points = self.max_available_points * (self.safety_buffer_points / self.max_available_points if self.max_available_points > 0 else 0.25)


            # print(f"Throttle status updated: Available={self.currently_available_points}, Max={self.max_available_points}, RestoreRate={self.restore_rate}")

    def _make_request(self, query: str, variables: dict = None, estimated_cost: int = 10):
        """
        Makes a GraphQL request to Shopify, handling rate limits.
        estimated_cost: A rough estimate of the query cost to check against the safety buffer.
        """
        
        # Proactive check: Wait if available points are below safety buffer + estimated cost for next query
        required_points_for_next_op = estimated_cost + self.safety_buffer_points
        
        if self.currently_available_points < required_points_for_next_op:
            points_needed = required_points_for_next_op - self.currently_available_points
            wait_time = (points_needed / self.restore_rate) if self.restore_rate > 0 else 10 # Default wait if rate is 0
            wait_time = max(wait_time, 0) + 0.5 # Add a small buffer
            
            print(f"Rate limit approaching: Only {self.currently_available_points} points available. Need ~{required_points_for_next_op}. Waiting for {wait_time:.2f} seconds...")
            time.sleep(wait_time)
            # Optimistically update available points after waiting, assuming they restored.
            # A more robust solution might re-check, but Shopify updates us after the call.
            self.currently_available_points = min(self.max_available_points, self.currently_available_points + (self.restore_rate * wait_time))


        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            # print(f"Executing query: {query[:100]}...") # Log snippet of query
            response = requests.post(self.graphql_url, headers=self.headers, json=payload, timeout=30) # Added timeout
            response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
            
            response_data = response.json()
            
            # Update throttle status from response
            if "extensions" in response_data:
                self._update_throttle_status(response_data["extensions"])

            if "errors" in response_data:
                raise ShopifyGraphQLError(response_data["errors"])

            return response_data.get("data")

        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP error occurred: {http_err} - {response.text}")
            # Potentially update throttle status if it's a 429 (Too Many Requests)
            if response.status_code == 429:
                 print("Received 429 Too Many Requests. Shopify might be applying additional throttling.")
                 # You might get a Retry-After header here or in extensions
                 retry_after_header = response.headers.get("Retry-After")
                 if retry_after_header:
                     print(f"Retry-After header suggests waiting {retry_after_header} seconds.")
                     # Implement a wait based on this if needed
                 # For now, force our available points low to trigger internal wait next time.
                 self.currently_available_points = 0 
            raise # Re-raise the exception
        except requests.exceptions.RequestException as req_err:
            print(f"Request error occurred: {req_err}")
            raise
        except json.JSONDecodeError:
            print(f"Failed to decode JSON response. Content: {response.text}")
            raise ShopifyGraphQLError([{"message": "Failed to decode JSON response", "response_text": response.text}])

    # --- Public methods for specific queries ---

    def get_products_count(self):
        """Fetches the total count of products in the store."""
        query = """
        query {
          productsCount {
            count
          }
        }
        """
        # productsCount is very cheap, default estimated_cost of 10 is fine.
        data = self._make_request(query)
        return data["productsCount"]["count"] if data and "productsCount" in data else None

    def get_all_products_summary(self, 
                                    online_store_publication_gid: str = None,
                                    query_filter: str = None, 
                                    page_size: int = 250):
        """
        Fetches a summary for all products, handling pagination.
        Optionally includes whether each product is published to the specified Online Store publication.
        
        :param online_store_publication_gid: GID of the 'Online Store' sales channel.
        :param query_filter: Optional Shopify product query string.
        :param page_size: Number of products to fetch per API call.
        :return: A list of product summary dictionaries.
        """
        all_products_summary = []
        has_next_page = True
        after_cursor = None
        
        query_filter_arg = ""
        if query_filter:
            query_filter_arg = f', query: "{query_filter}"'

        # Conditionally add publishedOnPublication to the query
        published_on_online_store_field = ""
        variables = {"first": page_size, "after": after_cursor} # Initial variables

        if online_store_publication_gid:
            # Note: We need to pass onlineStorePublicationGid as a variable to the query
            # The query definition needs to declare it: $onlineStorePublicationGid: ID!
            # And the field usage: publishedOnPublication(publicationId: $onlineStorePublicationGid)
            published_on_online_store_field = "isPublishedOnlineStore: publishedOnPublication(publicationId: $onlineStorePublicationGid)"
            # Add to variables if GID is provided (will be used by _make_request)
            # variables["onlineStorePublicationGid"] = online_store_publication_gid 
            # ^ This approach requires _make_request to know about specific variables.
            # A simpler way for now is to embed it if we are not making it a query variable,
            # but that's not best practice for GIDs. Let's make it a proper query variable.
        
        # Build query arguments definition and pass-through strings
        query_args_def_list = ["$first: Int!"]
        query_args_pass_list = ["first: $first"]

        if after_cursor: # This variable is set in the loop, not initial call
            query_args_def_list.append("$after: String")
            query_args_pass_list.append("after: $after")
        
        if query_filter:
            query_args_def_list.append("$queryFilter: String") # Renamed to avoid conflict
            query_args_pass_list.append("query: $queryFilter")
            # variables["queryFilter"] = query_filter # This will be added later in the loop setup

        if online_store_publication_gid:
            query_args_def_list.append("$onlineStorePublicationGid: ID!")
            query_args_pass_list.append(published_on_online_store_field) # The field itself uses the var
            # variables["onlineStorePublicationGid"] = online_store_publication_gid # This will be added later

        query_args_def_str = ", ".join(query_args_def_list)
        # For the 'products' arguments, we build it slightly differently
        products_args_list = ["first: $first"]
        if after_cursor: products_args_list.append("after: $after")
        if query_filter: products_args_list.append("query: $queryFilter")
        products_args_str = ", ".join(products_args_list)


        # The actual field in Product node that uses $onlineStorePublicationGid
        # will be constructed based on published_on_online_store_field
        # For clarity, the `published_on_online_store_field` variable will just be the field name string.
        # The GID will be passed via variables.
        
        published_field_for_query = ""
        if online_store_publication_gid:
            published_field_for_query = "isPublishedOnlineStore: publishedOnPublication(publicationId: $onlineStorePublicationGid)"


        # base_query_template = f"""
        # query getAllProductsSummaryWithPublishStatus({query_args_def_str}) {{
        #   products({products_args_str}) {{
        #     pageInfo {{
        #       hasNextPage
        #       endCursor
        #     }}
        #     edges {{
        #       node {{
        #         id
        #         descriptionHtml
        #         category {{
        #             fullName
        #             id
        #             name
        #             parentId
        #         }}
        #         legacyResourceId
        #         createdAt
        #         handle
        #         title
        #         description
        #         status
        #         vendor
        #         onlineStorePreviewUrl
        #         onlineStoreUrl
        #         resourcePublicationsCount
        #         productType
        #         {published_field_for_query}
        #       }}
        #     }}
        #   }}
        # }}
        # """
        
        print(f"Fetching all product summaries (page size: {page_size})...")
        page_num = 1
        
        # Initial variables for the first call
        current_vars = {"first": page_size}
        if query_filter:
            current_vars["queryFilter"] = query_filter
        if online_store_publication_gid:
            current_vars["onlineStorePublicationGid"] = online_store_publication_gid

        while has_next_page:
            # Update query string for current 'after_cursor' state in arguments definition
            current_query_args_def_list = ["$first: Int!"]
            current_products_args_list = ["first: $first"]

            if after_cursor:
                current_query_args_def_list.append("$after: String")
                current_products_args_list.append("after: $after")
                current_vars["after"] = after_cursor # Add/update after cursor in variables
            elif "after" in current_vars:
                del current_vars["after"] # Remove if no longer needed

            if query_filter:
                current_query_args_def_list.append("$queryFilter: String")
                current_products_args_list.append("query: $queryFilter")
            
            if online_store_publication_gid:
                current_query_args_def_list.append("$onlineStorePublicationGid: ID!")
                # published_field_for_query is already defined with the $variable

            final_query_args_def_str = ", ".join(current_query_args_def_list)
            final_products_args_str = ", ".join(current_products_args_list)
            
            # Reconstruct the query string for each page to correctly include/exclude $after
            current_query = f"""
            query getAllProductsSummaryWithPublishStatus({final_query_args_def_str}) {{
              products({final_products_args_str}) {{
                pageInfo {{
                  hasNextPage
                  endCursor
                }}
                edges {{
                  node {{
                    id
                    handle
                    title
                    vendor
                    productType
                    tags
                    metafields(first: 10) {{
                      nodes {{
                        id
                        jsonValue
                        key
                        type
                        updatedAt
                        value
                        legacyResourceId
                        namespace
                        
                      }}
                    }}
                    publishedAt
                    status
                    createdAt
                    updatedAt
                    tracksInventory
                    totalInventory
                    totalVariants
                    onlineStorePreviewUrl
                    onlineStoreUrl
                    legacyResourceId
                    category {{
                        fullName
                        id
                        name
                        parentId
                    }}
                    
                    description
                    descriptionHtml
                    featuredMedia {{
                      id
                      alt
                    }}
                    seo {{
                      description
                      title
                    }}
                    variantsCount {{
                      count
                      precision
                    }}
                    variants(first: 10) {{
                      nodes {{
                        sku
                        availableForSale
                        price
                        inventoryPolicy
                        inventoryItem {{
                          requiresShipping
                          unitCost {{
                            amount
                            currencyCode
                          }}
                          tracked
                          sku
                        }}
                        inventoryQuantity
                        position
                        compareAtPrice
                        displayName
                        title
                      }}
                    }}
                    mediaCount {{
                      count
                      precision
                    }}
                    media(first: 25) {{
                      edges {{
                        node {{
                          id
                          mediaContentType
                          preview {{
                            image {{
                              url
                              altText
                            }}
                            status
                          }}
                        }}
                      }}
                    }}
                    resourcePublicationsCount {{
                      count
                      precision
                    }}
                    resourcePublications(first: 10) {{
                      nodes {{
                        isPublished
                        publishDate
                        publication {{
                          catalog {{
                            title
                            status
                          }}
                        }}
                      }}
                    }}
                    options(first: 100) {{
                      id
                      linkedMetafield {{
                        key
                        namespace
                      }}
                      name
                      optionValues {{
                        hasVariants
                        id
                        linkedMetafieldValue
                        name
                        swatch {{
                          color
                        }}
                        translations(locale: "") {{
                          key
                          locale
                          outdated
                          updatedAt
                          value
                        }}
                      }}
                      position
                      translations(locale: "") {{
                        key
                      }}
                      values
                    }}
                    {published_field_for_query}
                  }}
                }}
              }}
            }}
            """
            # print(f"DEBUG Query: {current_query}") # For debugging the query string
            # print(f"DEBUG Vars: {current_vars}")   # For debugging variables

            estimated_cost_for_page = 10 + (page_size // 10) + (5 if online_store_publication_gid else 0)

            print(f"Fetching page {page_num} (after cursor: {after_cursor})...")
            data = self._make_request(current_query, current_vars, estimated_cost=estimated_cost_for_page)
            
            if data and "products" in data:
                products_data = data["products"]
                for edge in products_data.get("edges", []):
                    all_products_summary.append(edge["node"])
                
                page_info = products_data.get("pageInfo", {})
                has_next_page = page_info.get("hasNextPage", False)
                after_cursor = page_info.get("endCursor") # This will be used in the next iteration's current_vars
                page_num += 1
                
                if not has_next_page:
                    print("Fetched all product summaries.")
            else:
                print("No product data returned or unexpected response structure for this page.")
                break 
            
            if has_next_page:
                time.sleep(0.01) 

        return all_products_summary

    def get_product_snapshot_by_id(self, product_gid: str,
                                   num_variants: int = 50,
                                   num_images: int = 20,
                                   num_metafields: int = 10,
                                   metafield_namespace: str = None):
        """
        Fetches a comprehensive snapshot of a single product by its GraphQL GID.
        Includes product details, options, variants, images, and optionally metafields.
        """
        metafields_query_part = ""
        # (Metafields query part logic remains the same as before)
        if metafield_namespace:
            metafields_query_part = f"""
          metafields(first: $numMetafields, namespace: "{metafield_namespace}") {{
            edges {{ node {{ id legacyResourceId key namespace value type description createdAt updatedAt }} }}
          }}
        """
        elif num_metafields > 0 and metafield_namespace is None:
             metafields_query_part = f"""
          metafields(first: $numMetafields) {{
            edges {{ node {{ id legacyResourceId key namespace value type description createdAt updatedAt }} }}
          }}
        """

        query = f"""
        query getProductSnapshot($id: ID!, $numVariants: Int!, $numImages: Int!{', $numMetafields: Int!' if metafields_query_part else ''}) {{
          node(id: $id) {{
            ... on Product {{
              id
              legacyResourceId
              handle
              title
              descriptionHtml
              vendor
              productType
              productCategory {{ productTaxonomyNode {{ name fullName }} }}
              category {{ id name fullName }}
              seo {{ title description }}
              status
              onlineStoreUrl
              onlineStorePreviewUrl
              publishedAt
              createdAt
              updatedAt
              tags
              options {{ id name position values }}
              variants(first: $numVariants) {{
                pageInfo {{ hasNextPage endCursor }}
                edges {{
                  node {{
                    id
                    legacyResourceId
                    title
                    sku
                    barcode
                    price
                    compareAtPrice
                    inventoryQuantity
                    inventoryPolicy  # Replaced inventoryManagement
                    inventoryItem {{ # To check if tracked by Shopify
                        id
                        legacyResourceId
                        sku 
                        tracked
                        requiresShipping
                        # variant #
                        measurement {{
                            weight {{
                                value
                                unit
                            }}
                        }}
                        # unitCost {{ amount currencyCode }} # This is how you comment it in GraphQL - double brackets
                        # countryCodeOfOrigin # If needed
                        # harmonizedSystemCode # If needed
                    }}
                    position
                    image {{ id url(transform: {{maxWidth: 800, maxHeight: 800}}) altText }}
                    selectedOptions {{ name value }}
                    # The following fields (weight, weightUnit) caused errors.
                    # Verify them in your GraphiQL explorer for your API version.
                    # They ARE standard fields, but might be missing if products have no weight 
                    # or if there's an API version mismatch making them unavailable as queried.
                    # For now, let's try querying them. If errors persist, you may need to remove them
                    # or ensure your products have weight data.
                  }}
                }}
              }}
              images(first: $numImages) {{
                pageInfo {{ hasNextPage endCursor }}
                edges {{ node {{ id url(transform: {{maxWidth: 1024, maxHeight: 1024}}) altText width height }} }}
              }}
              {metafields_query_part}
            }}
        }}
        }}
        """
        variables = {
            "id": product_gid,
            "numVariants": num_variants,
            "numImages": num_images,
            "numMetafields": num_metafields
        }
        
        estimated_cost = 50 + (num_variants // 10) + (num_images // 10) + (num_metafields // 10)
        
        data = self._make_request(query, variables, estimated_cost=estimated_cost)
        return data["node"] if data and "node" in data else None

    # ------------------------------------------------------------------
    # Metafield helpers
    # ------------------------------------------------------------------

    def create_metafield_definition(
        self,
        *,
        name: str,
        namespace: str,
        key: str,
        type_name: str,
        owner_type: str = "PRODUCT",
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        mutation = """
        mutation metafieldDefinitionCreate($definition: MetafieldDefinitionInput!) {
          metafieldDefinitionCreate(definition: $definition) {
            createdDefinition { id name namespace key }
            userErrors { field message code }
          }
        }
        """
        definition_input = {
            "name": name,
            "namespace": namespace,
            "key": key,
            "type": type_name,
            "ownerType": owner_type,
        }
        if description:
            definition_input["description"] = description

        variables = {"definition": definition_input}
        data = self._make_request(mutation, variables, estimated_cost=10)
        return data.get("metafieldDefinitionCreate", {}) if data else {}

    def set_metafields(self, metafields: List[Dict[str, Any]]) -> Dict[str, Any]:
        mutation = """
        mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
          metafieldsSet(metafields: $metafields) {
            metafields { id namespace key value type }
            userErrors { field message code }
          }
        }
        """
        variables = {"metafields": metafields}
        data = self._make_request(mutation, variables, estimated_cost=10)
        return data.get("metafieldsSet", {}) if data else {}

    def update_inventory_item(self, item_gid: str, *, country_code: Optional[str] = None,
                              harmonized_code: Optional[str] = None,
                              province_code: Optional[str] = None) -> Dict[str, Any]:
        if not (country_code or harmonized_code or province_code):
            return {}
        mutation = """
        mutation inventoryItemUpdate($id: ID!, $input: InventoryItemInput!) {
          inventoryItemUpdate(id: $id, input: $input) {
            inventoryItem {
              id
              countryCodeOfOrigin
              provinceCodeOfOrigin
              harmonizedSystemCode
            }
            userErrors { field message }
          }
        }
        """
        input_payload: Dict[str, Any] = {}
        if country_code:
            input_payload["countryCodeOfOrigin"] = country_code
        if harmonized_code:
            input_payload["harmonizedSystemCode"] = harmonized_code
        if province_code:
            input_payload["provinceCodeOfOrigin"] = province_code

        variables = {"id": item_gid, "input": input_payload}
        logger.info(
            "Shopify inventoryItemUpdate payload: id=%s input=%s",
            item_gid,
            json.dumps(input_payload),
        )
        data = self._make_request(mutation, variables, estimated_cost=10)
        return data.get("inventoryItemUpdate", {}) if data else {}

    def get_shop_locations(self, num_locations: int = 5, query_filter: str = None): # Added query_filter capability
        """
        Fetches the shop's locations directly from QueryRoot.
        Requires 'read_locations' scope.
        """
        # Constructing the arguments string for the locations query
        # Handles 'first' and potentially 'query' if you want to filter locations by name, etc.
        args_list = [f"first: {num_locations}"]
        if query_filter:
            args_list.append(f'query: "{query_filter}"')
        # Add other arguments like 'after', 'sortKey' as needed for full pagination/sorting
        
        args_string = ", ".join(args_list)

        query = f"""
        query GetShopLocations {{
          locations({args_string}) {{ # Querying locations directly from QueryRoot
            edges {{
              node {{
                id
                legacyResourceId
                name
                isActive
                address {{
                  address1
                  address2 # Added address2
                  city
                  zip
                  country
                  countryCode
                  province # Added province
                  phone
                }}
                # You might also be interested in:
                # hasInventory
                # shipsInventory
                # fulfillsOnlineOrders
              }}
            }}
            pageInfo {{
              hasNextPage
              endCursor
            }}
          }}
        }}
        """
        # This query is usually low cost.
        estimated_cost = 10 
        # No 'variables' needed if 'first' is embedded in query string,
        # but using variables is cleaner if more args are added. Let's adjust to use variables.

        query_with_vars = """
        query GetShopLocations($first: Int!, $query: String) {
          locations(first: $first, query: $query) { # Using variables
            edges {
              node {
                id
                legacyResourceId
                name
                isActive
                address {
                  address1
                  address2
                  city
                  zip
                  country
                  countryCode
                  province
                  phone
                }
              }
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
        variables = {"first": num_locations}
        if query_filter:
            variables["query"] = query_filter
        else:
            # GraphQL requires all declared variables to be passed, even if null
            # or you can conditionally build the query string to omit the query arg if not provided.
            # For simplicity here, we'll pass null if no filter. Some APIs require optional args to be omitted.
            # A better way is to dynamically build the (query: $query) part.
            # Let's adjust the query string itself if no filter for cleaner API call.
            query_args_def = "$first: Int!"
            query_args_pass = "first: $first"
            if query_filter:
                query_args_def += ", $query: String"
                query_args_pass += ", query: $query"

            query_final = f"""
            query GetShopLocations({query_args_def}) {{
              locations({query_args_pass}) {{
                edges {{
                  node {{
                    id
                    legacyResourceId
                    name
                    isActive
                    address {{
                      address1
                      address2
                      city
                      zip
                      country
                      countryCode
                      province
                      phone
                    }}
                  }}
                }}
                pageInfo {{
                  hasNextPage
                  endCursor
                }}
              }}
            }}
            """
        
        data = self._make_request(query_final, variables, estimated_cost=estimated_cost)
        # The response structure will now have 'locations' directly under 'data'
        return data["locations"] if data and "locations" in data else None

    def get_online_store_publication_id(self):
        """
        Fetches the GID of the 'Online Store' publication (sales channel).
        Requires 'read_publications' scope.
        Returns the GID string if found, otherwise None.
        """
        query = """
        query GetOnlineStorePublication {
          publications(first: 20) { # Fetch up to 20, usually there are few
            edges {
              node {
                id
                name
                # app { # Temporarily remove or verify App fields if needed later
                #   name 
                # }
              }
            }
          }
        }
        """
        estimated_cost = 5 # Reduced cost as it's a simpler query now
        
        print("Fetching publications to find 'Online Store' GID...")
        data = self._make_request(query, estimated_cost=estimated_cost)
        
        if data and data.get("publications") and data["publications"].get("edges"):
            found_online_store = False
            online_store_gid = None
            print("\n--- Available Publications ---") # Print all found for easier identification
            for edge in data["publications"]["edges"]:
                node = edge.get("node")
                if node:
                    publication_id = node.get('id')
                    publication_name = node.get("name", "Unknown Name")
                    print(f"  Found: Name='{publication_name}', GID='{publication_id}'")
                    if publication_name.lower() == "online store":
                        online_store_gid = publication_id
                        found_online_store = True
                        print(f"    ^^^ Identified 'Online Store' publication ^^^")
            
            if found_online_store:
                return online_store_gid
            else:
                print("\nWarning: 'Online Store' publication not found by that exact name.")
                print("Please review the list above and identify the correct GID for your online store sales channel.")
                return None
        else:
            print("Could not retrieve publications or response structure was unexpected.")
            if data:
                print(f"Received data: {data}")
            return None

    def get_variant_details_rest(self, variant_gid: str):
        """
        Gets variant details using REST API to verify it exists.
        """
        import requests
        
        variant_id = variant_gid.split('/')[-1]
        clean_domain = self.store_domain.rstrip('/')
        
        rest_url = f"https://{clean_domain}/admin/api/{self.api_version}/variants/{variant_id}.json"
        
        headers = {
            "X-Shopify-Access-Token": self.admin_api_token,
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(rest_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            return response.json().get("variant", {})
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching variant {variant_id}: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Response status: {e.response.status_code}")
                print(f"Response content: {e.response.text}")
            return None

    def get_product_categories(self, search_term: str = None, limit: int = 50):
        """
        Alternative approach: Get existing product categories from products already in store.
        Since productTaxonomyNodes isn't available, we'll use productCategory field from existing products.
        
        TODO: Fix GraphQL parentId field error - currently commented out
        """
        # COMMENTED OUT DUE TO GraphQL parentId FIELD ERROR
        # Will fix this later when we enhance category management
        print(f"⚠️ Category lookup temporarily disabled due to GraphQL field error")
        return []
      
        # query = """
        # query getExistingCategories($first: Int!) {
        #   products(first: $first) {
        #     edges {
        #       node {
        #         productCategory {
        #           productTaxonomyNode {
        #             id
        #             name
        #             fullName
        #             parentId
        #           }
        #         }
        #       }
        #     }
        #   }
        # }
        # """
        
        # variables = {"first": limit}
        # estimated_cost = 10
        
        # try:
        #     data = self._make_request(query, variables, estimated_cost=estimated_cost)
        #     if data and data.get("products"):
        #         # Extract unique categories from existing products
        #         categories = []
        #         seen_ids = set()
        
        #         for edge in data["products"]["edges"]:
        #             node = edge["node"]
        #             if node.get("productCategory") and node["productCategory"].get("productTaxonomyNode"):
        #                 cat_node = node["productCategory"]["productTaxonomyNode"]
        #                 if cat_node.get("id") and cat_node["id"] not in seen_ids:
        #                     categories.append({"node": cat_node})
        #                     seen_ids.add(cat_node["id"])
        
        #         # Filter by search term if provided
        #         if search_term:
        #             search_lower = search_term.lower()
        #             filtered_categories = []
        #             for cat in categories:
        #                 node = cat["node"]
        #                 if (search_lower in node.get("name", "").lower() or 
        #                     search_lower in node.get("fullName", "").lower()):
        #                     filtered_categories.append(cat)
        #             return filtered_categories
                
        #         return categories
        #     return []
        # except Exception as e:
        #     print(f"Error fetching existing product categories: {e}")
        #     return []

    def find_category_gid(self, category_name: str):
        """
        Enhanced category finder that falls back to common Shopify categories.
        Uses dynamic lookup instead of hardcoded GIDs.
        
        TODO: Currently returns None due to category lookup being disabled
        """
        
            # Temporarily return None since category lookup is disabled
        print(f"⚠️ Category lookup disabled - using direct GID assignment instead")
        return None
        
        if not category_name or not category_name.strip():
            return None
        
        category_name = category_name.strip()
        print(f"🔍 Searching for category: '{category_name}'")
        
        # Try to find from existing products first
        categories = self.get_product_categories(search_term=category_name)
        
        if categories:
            # Look for exact match first
            for cat in categories:
                node = cat["node"]
                if (node.get("name", "").lower() == category_name.lower() or 
                    node.get("fullName", "").lower() == category_name.lower()):
                    print(f"✅ Found exact category match: '{node.get('fullName')}' -> {node.get('id')}")
                    return node.get("id")
            
            # If no exact match, return the first result
            first_node = categories[0]["node"]
            print(f"⚠️ Using closest category match: '{category_name}' -> '{first_node.get('fullName')}' ({first_node.get('id')})")
            return first_node.get("id")
        
        # Try searching for broader terms if specific search failed
        broader_searches = []
        category_lower = category_name.lower()
        
        if "bass" in category_lower:
            broader_searches = ["bass", "string instruments", "musical instruments"]
        elif "guitar" in category_lower:
            broader_searches = ["guitar", "string instruments", "musical instruments"]
        elif "amplifier" in category_lower or "amp" in category_lower:
            broader_searches = ["amplifier", "audio", "musical instruments"]
        elif "instrument" in category_lower:
            broader_searches = ["musical instruments", "music"]
        else:
            # Try searching for individual words
            words = category_name.split()
            broader_searches = [word for word in words if len(word) > 3]
        
        # Try each broader search term
        for search_term in broader_searches:
            print(f"🔍 Trying broader search: '{search_term}'")
            categories = self.get_product_categories(search_term=search_term)
            if categories:
                first_node = categories[0]["node"]
                print(f"⚠️ Using broad category match: '{category_name}' -> '{first_node.get('fullName')}' ({first_node.get('id')})")
                return first_node.get("id")
        
        print(f"❌ No category found for: '{category_name}' - product will use default category")
        return None

    def set_product_category(self, product_gid: str, category_gid: str):
        """
        Sets the category for an existing product using productUpdate.
        """
        if not category_gid:
            return False
        
        try:
            product_input = {
                "id": product_gid,
                "category": category_gid
            }
            
            result = self.update_product(product_input)
            if result and result.get("product"):
                print(f"✅ Category updated for product {product_gid}")
                return True
            else:
                print(f"⚠️ Category update failed for product {product_gid}")
                return False
        except Exception as e:
            print(f"❌ Error updating category for product {product_gid}: {e}")
            return False

# --- POST methods for product management ---

    # Core Product Management 
    def create_product(self, product_input: dict):
        """
        Creates a new product using the productCreate mutation.
        product_input: A dictionary matching the ProductInput GraphQL type.
                       See https://shopify.dev/docs/api/admin-graphql/latest/inputs/ProductInput
        """
        mutation = """
        mutation productCreate($input: ProductInput!) {
          productCreate(input: $input) {
            product {
              id
              legacyResourceId
              handle
              title
              variants(first: 5) { # Get a few variants back for confirmation
                edges {
                  node {
                    id
                    legacyResourceId
                    title
                    sku
                    price
                  }
                }
              }
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        variables = {"input": product_input}
        # Product creation can be moderately expensive, especially with variants and images
        estimated_cost = 50 + (len(product_input.get("variants", [])) * 5) + (len(product_input.get("images", [])) * 5)
        
        data = self._make_request(mutation, variables, estimated_cost=estimated_cost)
        # self._make_request will raise ShopifyGraphQLError if userErrors are present and significant
        # For productCreate, userErrors might be present even on partial success for some sub-fields.
        # Here we explicitly check userErrors from the payload as well.
        if data and data.get("productCreate") and data["productCreate"].get("userErrors"):
            errors = data["productCreate"]["userErrors"]
            if errors: # Check if the list is not empty
                # You might want to log these or handle them more gracefully
                # For now, we'll raise if there are any user errors reported at this level
                # This behaviour can be adjusted based on how strictly you want to treat partial successes
                print(f"Warning/UserErrors during productCreate for handle '{product_input.get('handle', 'N/A')}': {errors}")
                # Depending on severity, you might not want to raise an exception here if product was still created
                # For example, if product is created but an image failed.
                # The current _make_request will raise if there are top-level errors.
                # This explicit check is for userErrors specific to productCreate payload.
        
        return data["productCreate"] if data and "productCreate" in data else None

    def update_product(self, product_input: dict):
        """
        Updates an existing product using the productUpdate mutation.
        product_input: A dictionary matching the ProductInput GraphQL type.
                       MUST include the 'id' (GID) of the product to update.
                       Only include fields you want to change.
        """
        if not product_input.get("id"):
            raise ValueError("Product GID ('id') must be included in product_input for updates.")

        mutation = """
        mutation productUpdate($input: ProductInput!) {
          productUpdate(input: $input) {
            product {
              id
              legacyResourceId
              handle
              title
              updatedAt
              # Add other fields you want to see in the response
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        variables = {"input": product_input}
        # Update cost can vary widely based on what's being changed
        estimated_cost = 30 + (len(product_input.get("variants", [])) * 5) + (len(product_input.get("images", [])) * 5)
        
        data = self._make_request(mutation, variables, estimated_cost=estimated_cost)
        
        if data and data.get("productUpdate") and data["productUpdate"].get("userErrors"):
            errors = data["productUpdate"]["userErrors"]
            if errors:
                 print(f"Warning/UserErrors during productUpdate for ID '{product_input.get('id', 'N/A')}': {errors}")

        return data["productUpdate"] if data and "productUpdate" in data else None
    
    def delete_product(self, product_gid: str):
        """
        Deletes a product using the productDelete mutation.
        product_gid: The GID (e.g., "gid://shopify/Product/123") of the product to delete.
        """
        mutation = """
        mutation productDelete($input: ProductDeleteInput!) {
          productDelete(input: $input) {
            deletedProductId
            shop {
              id # To confirm context
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        variables = {"input": {"id": product_gid}}
        estimated_cost = 20 # Deletion is usually cheaper
        
        data = self._make_request(mutation, variables, estimated_cost=estimated_cost)
        if data and data.get("productDelete") and data["productDelete"].get("userErrors"):
            errors = data["productDelete"]["userErrors"]
            if errors:
                 print(f"Warning/UserErrors during productDelete for ID '{product_gid}': {errors}")
        
        return data["productDelete"] if data and "productDelete" in data else None

    async def mark_product_as_sold(self, product_gid: str, reduce_by: int = 1) -> dict:
        """
        Mark a product as sold by reducing inventory and verifying success
        
        Args:
            product_gid: Shopify product GID
            reduce_by: Amount to reduce inventory by (default 1)
            
        Returns:
            dict: Success status and inventory details
        """
        try:
            logger.info(f"Marking Shopify product as sold: {product_gid}")
            
            # Step 1: Reduce inventory
            inventory_updates = {
                "inventory": f"-{reduce_by}",  # Reduce by specified amount
                "tags": ["sold-via-sync", f"reduced-{datetime.now().strftime('%Y%m%d-%H%M%S')}"]
            }
            
            # This correctly runs the synchronous code in the background
            loop = asyncio.get_running_loop()
            update_success = await loop.run_in_executor(
                None, self.update_complete_product, product_gid, inventory_updates
            )
            
            if not update_success:
                return {
                    "success": False,
                    "error": "Failed to update inventory",
                    "step": "inventory_update"
                }
            
            # Step 2: Verify the change worked
            verify_result = await self._verify_inventory_change(product_gid)
            
            if verify_result.get("success"):
                return {
                    "success": True,
                    "product_gid": product_gid,
                    "previous_quantity": verify_result.get("previous_quantity"),
                    "new_quantity": verify_result.get("new_quantity"),
                    "status": verify_result.get("product_status"),
                    "step": "completed"
                }
            else:
                return {
                    "success": False,
                    "error": "Inventory update verification failed",
                    "step": "verification"
                }
                
        except Exception as e:
            logger.error(f"Error marking Shopify product as sold: {e}")
            return {
                "success": False,
                "error": str(e),
                "step": "exception"
            }

    async def _verify_inventory_change(self, product_gid: str) -> dict:
        """Verify inventory change via fresh GraphQL query"""
        try:
            verify_query = """
            query getProductInventory($id: ID!) {
              product(id: $id) {
                id
                title
                status
                variants(first: 1) {
                  edges {
                    node {
                      id
                      sku
                      inventoryQuantity
                    }
                  }
                }
              }
            }
            """
            
            result = self._make_request(verify_query, {"id": product_gid}, estimated_cost=5)
            
            if result and result.get("product"):
                product = result["product"]
                if product.get("variants", {}).get("edges"):
                    variant = product["variants"]["edges"][0]["node"]
                    
                    return {
                        "success": True,
                        "product_status": product.get("status"),
                        "new_quantity": variant.get("inventoryQuantity"),
                        "variant_sku": variant.get("sku")
                    }
            
            return {"success": False, "error": "Could not verify inventory"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Unified Workflow - main workhorse!
    def update_complete_product(self, product_gid: str, product_updates: dict):
            """
            Updates a complete product including its basic info and pricing/inventory.
            This handles both the product data and its default variant data.
            """
            
            # 1. Update product basic info (title, description, etc.)
            if any(key in product_updates for key in ['title', 'descriptionHtml', 'vendor', 'productType', 'tags']):
                product_input = {"id": product_gid}
                
                for field in ['title', 'descriptionHtml', 'vendor', 'productType', 'tags']:
                    if field in product_updates:
                        product_input[field] = product_updates[field]
                
                self.update_product(product_input)
                print("✅ Product info updated")
            
            # 2. Update pricing/inventory (stored in the variant)
            if any(key in product_updates for key in ['price', 'sku', 'inventory']):
                # Get the product's default variant
                product_data = self.get_product_snapshot_by_id(product_gid, num_variants=1)
                if product_data and product_data.get("variants", {}).get("edges"):
                    variant_gid = product_data["variants"]["edges"][0]["node"]["id"]
                    
                    variant_updates = {}
                    if 'price' in product_updates:
                        variant_updates['price'] = product_updates['price']
                    if 'sku' in product_updates:
                        variant_updates['sku'] = product_updates['sku']
                    if 'inventory' in product_updates:
                        variant_updates['inventoryQuantities'] = [{
                            "availableQuantity": product_updates['inventory'],
                            "locationId": "gid://shopify/Location/109766639956"  # Your location
                        }]
                        variant_updates['inventoryItem'] = {"tracked": True}
                        variant_updates['inventoryPolicy'] = "DENY"
                    
                    self.update_variant_rest(variant_gid, variant_updates)
                    print("✅ Product pricing/inventory updated")
            
            # 3. Add images if provided
            if 'images' in product_updates:
                self.create_product_images(product_gid, product_updates['images'])
                print("✅ Product images added")
            
            return True

    # Variant Operations REST-based (only reliable variant method)
    def update_variant_rest(self, variant_gid: str, variant_updates: dict):
        """
        Updates a product variant using Shopify's REST API.
        This is the most reliable method for variant updates.
        """
        import requests
        
        # Extract numeric ID from GID
        variant_id = variant_gid.split('/')[-1]
        
        # Clean store domain (remove trailing slash if present)
        clean_domain = self.store_domain.rstrip('/')
        
        # Build REST API URL
        rest_url = f"https://{clean_domain}/admin/api/{self.api_version}/variants/{variant_id}.json"
        
        print(f"🔗 REST URL: {rest_url}")  # Debug URL construction
        
        # Convert your GraphQL format to REST format
        rest_updates = {}
        
        if "price" in variant_updates:
            rest_updates["price"] = variant_updates["price"]
        if "sku" in variant_updates:
            rest_updates["sku"] = variant_updates["sku"]
        if "inventoryPolicy" in variant_updates:
            rest_updates["inventory_policy"] = variant_updates["inventoryPolicy"].lower()
        if "compare_at_price" in variant_updates:
          rest_updates["compare_at_price"] = variant_updates["compare_at_price"]
        
        # Handle inventory tracking
        if "inventoryItem" in variant_updates and "tracked" in variant_updates["inventoryItem"]:
            rest_updates["inventory_management"] = "shopify" if variant_updates["inventoryItem"]["tracked"] else None
        
        payload = {"variant": rest_updates}
        
        headers = {
            "X-Shopify-Access-Token": self.admin_api_token,
            "Content-Type": "application/json"
        }
        
        try:
            print(f"Making REST API call to update variant {variant_id}...")
            print(f"Payload: {json.dumps(payload, indent=2)}")  # Debug payload
            
            response = requests.put(rest_url, headers=headers, json=payload, timeout=30)
            
            print(f"Response status: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")
            
            response.raise_for_status()
            
            variant_data = response.json().get("variant", {})
            
            print(f"Raw API response: {response.json()}")
            
            # Handle inventory quantity separately if provided
            if "inventoryQuantities" in variant_updates:
                self._update_inventory_rest(variant_id, variant_updates["inventoryQuantities"])
            
            return {"variant": variant_data}
            
        except requests.exceptions.RequestException as e:
            print(f"REST API error updating variant {variant_id}: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Response status code: {e.response.status_code}")
                print(f"Response content: {e.response.text}")
            return None

    def delete_product_images_rest(self, product_gid: str, image_gids: List[str]) -> None:
        """Delete product images via REST API using image GIDs."""
        if not image_gids:
            return

        import requests

        product_id = product_gid.split('/')[-1]
        clean_domain = self.store_domain.rstrip('/')

        headers = {
            "X-Shopify-Access-Token": self.admin_api_token,
            "Content-Type": "application/json",
        }

        for gid in image_gids:
            image_id = gid.split('/')[-1]
            rest_url = (
                f"https://{clean_domain}/admin/api/{self.api_version}/products/{product_id}/images/{image_id}.json"
            )
            try:
                response = requests.delete(rest_url, headers=headers, timeout=30)
                if response.status_code not in (200, 204):
                    logger.warning(
                        "Failed to delete Shopify image %s (status=%s, body=%s)",
                        gid,
                        response.status_code,
                        response.text,
                    )
            except requests.exceptions.RequestException as exc:
                logger.warning("Error deleting Shopify image %s: %s", gid, exc)

    async def update_product_variant_price(self, product_gid: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update the primary variant price for a product using REST via executor."""

        if not payload or "price" not in payload:
            raise ValueError("Payload must include 'price' for Shopify variant updates")

        price_value = payload["price"]

        def _update_price() -> Dict[str, Any]:
            product_data = self.get_product_snapshot_by_id(product_gid, num_variants=1)
            if not product_data:
                raise ValueError(f"Unable to load product snapshot for {product_gid}")

            variants = (product_data.get("variants") or {}).get("edges") or []
            if not variants:
                raise ValueError(f"Product {product_gid} has no variants to update")

            variant_node = variants[0].get("node") or {}
            variant_gid = variant_node.get("id")
            if not variant_gid:
                raise ValueError(f"Variant ID missing for product {product_gid}")

            self.update_variant_rest(variant_gid, {"price": price_value})
            return {"success": True, "variant_id": variant_gid, "price": price_value}

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, _update_price)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to update Shopify variant price for %s: %s", product_gid, exc, exc_info=True)
            return {"success": False, "error": str(exc)}

    def _update_inventory_rest(self, variant_id: str, inventory_quantities: list):
        """
        Updates inventory quantities using REST API. Private helper.
        """
        import requests
        
        for inv_update in inventory_quantities:
            location_gid = inv_update["locationId"]
            location_id = location_gid.split('/')[-1]
            available_quantity = inv_update["availableQuantity"]
            
            try:
                # First, get the inventory item ID from the variant
                variant_url = f"https://{self.store_domain}/admin/api/{self.api_version}/variants/{variant_id}.json"
                headers = {"X-Shopify-Access-Token": self.admin_api_token}
                
                variant_response = requests.get(variant_url, headers=headers, timeout=30)
                variant_response.raise_for_status()
                
                inventory_item_id = variant_response.json()["variant"]["inventory_item_id"]
                
                # Set inventory level
                set_url = f"https://{self.store_domain}/admin/api/{self.api_version}/inventory_levels/set.json"
                set_payload = {
                    "location_id": int(location_id),
                    "inventory_item_id": inventory_item_id,
                    "available": available_quantity
                }
                
                set_response = requests.post(set_url, headers=headers, json=set_payload, timeout=30)
                set_response.raise_for_status()
                
                print(f"✅ Inventory updated for variant {variant_id} at location {location_id}: {available_quantity}")
                
            except requests.exceptions.RequestException as e:
                print(f"❌ Error updating inventory for variant {variant_id}: {e}")

    # Media & Publishing 
    def create_product_images(self, product_gid: str, images_data: list):
        """
        Creates product images using productCreateMedia mutation.
        """
        mutation = """
        mutation productCreateMedia($productId: ID!, $media: [CreateMediaInput!]!) {
        productCreateMedia(productId: $productId, media: $media) {
            media {
            ... on MediaImage {
                id
                image {
                url
                altText
                }
            }
            }
            mediaUserErrors {
            field
            message
            }
            userErrors {
            field
            message
            }
        }
        }
        """
        
        # Convert image URLs to media input format
        media_inputs = []
        for img_data in images_data:
            if isinstance(img_data, str):
                media_inputs.append({
                    "originalSource": img_data,
                    "mediaContentType": "IMAGE"
                })
            elif isinstance(img_data, dict):
                media_input = {
                    "originalSource": img_data.get("src") or img_data.get("url"),
                    "mediaContentType": "IMAGE"
                }
                if img_data.get("alt") or img_data.get("altText"):
                    media_input["alt"] = img_data.get("alt") or img_data.get("altText")
                media_inputs.append(media_input)
        
        variables = {
            "productId": product_gid,
            "media": media_inputs
        }
        estimated_cost = 15 + len(media_inputs) * 5
        
        data = self._make_request(mutation, variables, estimated_cost=estimated_cost)
        return data["productCreateMedia"] if data and "productCreateMedia" in data else None

    def publish_product_to_sales_channel(self, product_gid: str, publication_gid: str):
        """
        Publishes a product to a sales channel using publishablePublish mutation.
        """
        mutation = """
        mutation publishablePublish($id: ID!, $input: [PublicationInput!]!) {
        publishablePublish(id: $id, input: $input) {
            publishable {
            availablePublicationsCount {
                count
            }
            resourcePublicationsCount {
                count
            }
            }
            shop {
            id
            }
            userErrors {
            field
            message
            }
        }
        }
        """
        
        variables = {
            "id": product_gid,
            "input": [{"publicationId": publication_gid}]
        }
        estimated_cost = 20
        
        data = self._make_request(mutation, variables, estimated_cost=estimated_cost)
        return data["publishablePublish"] if data and "publishablePublish" in data else None

"""
Info for devs with no priors with SQLAlchemy to understand models:

The Python files in models correspond to database tables through SQLAlchemy's ORM (Object-Relational Mapper). 

SQLAlchemy Models and Database Tables
    1. Direct Table Correspondence: Each model class (like ShippingProfile) directly corresponds to a database 
        table (like shipping_profiles).
    2. OOP Representation: These models are Python classes that represent database tables in an object-oriented way. Instead of writing raw SQL queries, you can:
        - Create instances of these classes to add new rows
        - Query and filter these objects to retrieve data
        - Update attributes of these objects to update database records
        - Delete objects to remove database rows
    3. Column Definitions: Each attribute defined with Column() corresponds to a column in the database table:
        name = Column(String, nullable=False)  # Creates a non-nullable string column named "name"
    4. Relationships: The relationship() function defines how models are connected to each other:
        products = relationship("Product", back_populates="shipping_profile")
        
    This creates a Python-level connection between ShippingProfile and Product models that doesn't exist directly in the database tables (which use foreign keys).
    
    How It Works with the ShippingProfile model:
        - Corresponds to shipping_profiles table in the database
        - It defines columns like name, description, length, width, etc.
        - It has a relationship with the Product model via products
        - A foreign key in the Product model connects back to the shipping profile

Workflow Example for CRUD operations:
    # Create a new shipping profile
    new_profile = ShippingProfile(
        name="Guitar Case",
        description="Standard shipping box for guitars",
        length=135.0,
        width=60.0,
        height=20.0,
        weight=10.0,
        carriers=["dhl", "fedex"],
        options={"require_signature": True, "insurance": True},
        rates={"uk": 25.00, "europe": 50.00}
    )
    db.add(new_profile)
    await db.commit()

    # Query for shipping profiles
    guitar_profiles = await db.execute(
        select(ShippingProfile).where(ShippingProfile.name.contains("Guitar"))
    )
    results = guitar_profiles.scalars().all()

    # Update a shipping profile
    profile = await db.get(ShippingProfile, 1)
    profile.weight = 12.0
    await db.commit()

    # Delete a shipping profile
    profile = await db.get(ShippingProfile, 1)
    await db.delete(profile)
    await db.commit()

"""

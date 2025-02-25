class MockData:
    """Mock data for testing"""
    @staticmethod
    def get_test_urls():
        return {
            'images': [
                'https://example.com/test1.jpg',
                'https://example.com/test2.jpg'
            ],
            'videos': [
                'https://youtube.com/watch?v=example1',
                'https://youtube.com/watch?v=example2'
            ]
        }
    
    @staticmethod
    def get_test_categories():
        return {
            'main': ['51', '52', '53'],
            'sub': {
                '51': ['83', '84'],
                '52': ['85', '86']
            }
        }
from app import app
from routes import *
from admin_routes import *
from payment_handler import *

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

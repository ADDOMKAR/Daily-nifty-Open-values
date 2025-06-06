import requests
import json
import time
from datetime import datetime
import pytz
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SimpleStockBot:
    def __init__(self, telegram_bot_token, chat_id):
        self.bot_token = telegram_bot_token
        self.chat_id = chat_id
        self.telegram_url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
        
        # Headers to avoid blocking
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }
        
        # Create session with retry strategy
        self.session = self.create_session()
    
    def create_session(self):
        """Create a requests session with retry strategy"""
        session = requests.Session()
        
        # Define retry strategy
        retry_strategy = Retry(
            total=3,  # Total number of retries
            backoff_factor=1,  # Wait time between retries
            status_forcelist=[429, 500, 502, 503, 504],  # HTTP status codes to retry on
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]  # Methods to retry
        )
        
        # Mount adapter with retry strategy
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def get_simplified_stock_data(self):
        """Fetch only today's open and yesterday's OHLC data"""
        try:
            # Yahoo Finance symbols for Indian indices - Updated with multiple MidCap options
            symbols = {
                'NIFTY 50': '^NSEI',
                'NIFTY BANK': '^NSEBANK',
                'NIFTY MID SELECT': 'NIFTY_MID_SELECT.NS',  # Primary symbol
                'NIFTY FINANCIAL SERVICES': 'NIFTY_FIN_SERVICE.NS'
            }
            
            # Alternative symbols to try if primary fails
            alternative_symbols = {
                'NIFTY MID SELECT': [
                    'NIFTY_MID_SELECT.NS',  # Primary
                    '^NSEMDCP50',           # NIFTY MIDCAP 50 as backup
                    'NIFTY_MIDCAP_100.NS',  # NIFTY MIDCAP 100 as backup
                    'NIFTYMIDCAP150.NS'     # NIFTY MIDCAP 150 as backup
                ]
            }
            
            today_open_data = {}
            yesterday_data = {}
            
            for index_name, symbol in symbols.items():
                symbols_to_try = [symbol]
                
                # Add alternative symbols if available
                if index_name in alternative_symbols:
                    symbols_to_try = alternative_symbols[index_name]
                
                success = False
                for attempt_symbol in symbols_to_try:
                    try:
                        logger.info(f"Trying {index_name} with symbol: {attempt_symbol}")
                        
                        # Get 5 days of data to ensure we have both current and previous trading days
                        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{attempt_symbol}?range=5d&interval=1d"
                        
                        # Use session with retry mechanism
                        response = self.session.get(url, headers=self.headers, timeout=15)
                        
                        if response.status_code == 200:
                            data = response.json()
                            
                            # Check if we got valid data
                            if 'chart' not in data or not data['chart']['result']:
                                logger.warning(f"No chart data for {index_name} with {attempt_symbol}")
                                continue
                                
                            result = data['chart']['result'][0]
                            
                            # Check if required data exists
                            if not result.get('timestamp') or not result.get('indicators', {}).get('quote'):
                                logger.warning(f"Missing required data for {index_name} with {attempt_symbol}")
                                continue
                            
                            # Get historical data arrays
                            timestamps = result['timestamp']
                            quote_data = result['indicators']['quote'][0]
                            highs = quote_data.get('high', [])
                            lows = quote_data.get('low', [])
                            opens = quote_data.get('open', [])
                            closes = quote_data.get('close', [])
                            
                            # Convert timestamps to dates for easier handling
                            dates_data = []
                            for i, timestamp in enumerate(timestamps):
                                if (i < len(closes) and closes[i] is not None and 
                                    i < len(opens) and opens[i] is not None):  # Only include days with valid data
                                    date_obj = datetime.fromtimestamp(timestamp, tz=pytz.timezone('Asia/Kolkata'))
                                    dates_data.append({
                                        'date': date_obj.strftime('%Y-%m-%d'),
                                        'open': opens[i] if i < len(opens) else None,
                                        'close': closes[i] if i < len(closes) else None,
                                        'high': highs[i] if i < len(highs) else None,
                                        'low': lows[i] if i < len(lows) else None
                                    })
                            
                            # Sort by date (most recent first)
                            dates_data.sort(key=lambda x: x['date'], reverse=True)
                            
                            if len(dates_data) >= 2:
                                # Today's data (most recent trading day) - only open
                                today = dates_data[0]
                                today_open_data[index_name] = {
                                    'date': today['date'],
                                    'open': round(today['open'], 2) if today['open'] else 'N/A',
                                    'symbol_used': attempt_symbol  # Track which symbol worked
                                }
                                
                                # Yesterday's data (second most recent trading day) - OHLC
                                yesterday = dates_data[1]
                                yesterday_data[index_name] = {
                                    'date': yesterday['date'],
                                    'open': round(yesterday['open'], 2) if yesterday['open'] else 'N/A',
                                    'close': round(yesterday['close'], 2) if yesterday['close'] else 'N/A',
                                    'high': round(yesterday['high'], 2) if yesterday['high'] else 'N/A',
                                    'low': round(yesterday['low'], 2) if yesterday['low'] else 'N/A',
                                    'symbol_used': attempt_symbol  # Track which symbol worked
                                }
                                
                                logger.info(f"Successfully fetched data for {index_name} using {attempt_symbol}")
                                success = True
                                break  # Success, no need to try other symbols
                                
                        else:
                            logger.warning(f"HTTP {response.status_code} for {index_name} with {attempt_symbol}")
                            
                    except Exception as e:
                        logger.error(f"Error fetching {index_name} with {attempt_symbol}: {str(e)}")
                        continue
                    
                    time.sleep(0.3)  # Small delay between symbol attempts
                
                if not success:
                    logger.error(f"Failed to fetch data for {index_name} with all available symbols")
                    
                time.sleep(0.5)  # Small delay between different indices
            
            return today_open_data, yesterday_data
            
        except Exception as e:
            logger.error(f"Error in get_simplified_stock_data: {str(e)}")
            return {}, {}
    
    def format_simplified_message(self, today_open_data, yesterday_data):
        """Format simplified stock data into a readable message"""
        if not today_open_data and not yesterday_data:
            return "❌ Unable to fetch stock data at this time."
        
        ist = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(ist).strftime("%d-%m-%Y %H:%M:%S IST")
        
        message = f"👋 Hi Omkar!\n\n📊 *Simplified Stock Report*\n"
        message += f"🕘 Retrieved: {current_time}\n\n"
        
        # Get dates for headers
        today_date = ""
        yesterday_date = ""
        if today_open_data:
            today_date = list(today_open_data.values())[0].get('date', 'Today')
        if yesterday_data:
            yesterday_date = list(yesterday_data.values())[0].get('date', 'Yesterday')
        
        # Today's Opening Values
        message += f"🌅 *Today's Opening ({today_date})*\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        
        for index_name in today_open_data:
            values = today_open_data[index_name]
            symbol_info = f" [{values.get('symbol_used', 'N/A')}]" if 'symbol_used' in values else ""
            message += f"\n📈 *{index_name}*{symbol_info}\n"
            message += f"   Open: {values.get('open', 'N/A')}\n"
        
        # Yesterday's OHLC Values
        message += f"\n📊 *Yesterday's OHLC ({yesterday_date})*\n"
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        
        for index_name in yesterday_data:
            values = yesterday_data[index_name]
            symbol_info = f" [{values.get('symbol_used', 'N/A')}]" if 'symbol_used' in values else ""
            message += f"\n📉 *{index_name}*{symbol_info}\n"
            message += f"   Open: {values.get('open', 'N/A')}\n"
            message += f"   High: {values.get('high', 'N/A')}\n"
            message += f"   Low: {values.get('low', 'N/A')}\n"
            message += f"   Close: {values.get('close', 'N/A')}\n"
        
        # Add debug info for missing data
        all_expected_indices = {'NIFTY 50', 'NIFTY BANK', 'NIFTY MID SELECT', 'NIFTY FINANCIAL SERVICES'}
        missing_today = all_expected_indices - set(today_open_data.keys())
        missing_yesterday = all_expected_indices - set(yesterday_data.keys())
        
        if missing_today or missing_yesterday:
            message += f"\n⚠️ *Data Status*\n"
            if missing_today:
                message += f"Missing today's data: {', '.join(missing_today)}\n"
            if missing_yesterday:
                message += f"Missing yesterday's data: {', '.join(missing_yesterday)}\n"
        
        message += f"\n📱 *Stock Bot by Omkar*"
        return message
    
    def send_telegram_message(self, message, max_retries=3):
        """Send message to Telegram with retry mechanism"""
        for attempt in range(max_retries):
            try:
                payload = {
                    'chat_id': self.chat_id,
                    'text': message,
                    'parse_mode': 'Markdown'
                }
                
                # Use session with retry mechanism and longer timeout
                response = self.session.post(
                    self.telegram_url, 
                    json=payload, 
                    timeout=20,
                    headers={'Connection': 'close'}  # Force connection close
                )
                
                if response.status_code == 200:
                    logger.info("Message sent successfully to Telegram")
                    print("✅ Message sent to Telegram successfully!")
                    return True
                else:
                    logger.error(f"Failed to send message: {response.status_code} - {response.text}")
                    if attempt < max_retries - 1:
                        print(f"❌ Attempt {attempt + 1} failed, retrying in 2 seconds...")
                        time.sleep(2)
                    else:
                        print(f"❌ Failed to send message after {max_retries} attempts: {response.status_code}")
                        return False
                        
            except requests.exceptions.ConnectionError as e:
                logger.error(f"Connection error on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    print(f"🔄 Connection error, retrying in {2 * (attempt + 1)} seconds...")
                    time.sleep(2 * (attempt + 1))  # Exponential backoff
                else:
                    print(f"❌ Connection failed after {max_retries} attempts")
                    return False
                    
            except requests.exceptions.Timeout as e:
                logger.error(f"Timeout error on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    print(f"⏱️ Timeout error, retrying in {2 * (attempt + 1)} seconds...")
                    time.sleep(2 * (attempt + 1))
                else:
                    print(f"❌ Request timeout after {max_retries} attempts")
                    return False
                    
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    print(f"⚠️ Unexpected error, retrying in 3 seconds...")
                    time.sleep(3)
                else:
                    print(f"❌ Error sending message after {max_retries} attempts: {str(e)}")
                    return False
        
        return False
    
    def get_and_send_simplified_stock_data(self):
        """Main function to get and send simplified stock data (today's open + yesterday's OHLC)"""
        print("🔄 Fetching simplified stock data (today's open + yesterday's OHLC)...")
        
        # Get simplified data
        today_open_data, yesterday_data = self.get_simplified_stock_data()
        
        if today_open_data or yesterday_data:
            message = self.format_simplified_message(today_open_data, yesterday_data)
            success = self.send_telegram_message(message)
            if success:
                print("✅ Simplified stock data sent successfully!")
                print(f"🌅 Today's opening data: {len(today_open_data)} indices")
                print(f"📊 Yesterday's OHLC data: {len(yesterday_data)} indices")
                
                # Print detailed status
                print("\n📋 Data retrieval status:")
                all_indices = ['NIFTY 50', 'NIFTY BANK', 'NIFTY MID SELECT', 'NIFTY FINANCIAL SERVICES']
                for index in all_indices:
                    today_status = "✅" if index in today_open_data else "❌"
                    yesterday_status = "✅" if index in yesterday_data else "❌"
                    print(f"   {index}: Today {today_status} | Yesterday {yesterday_status}")
            else:
                print("❌ Failed to send simplified stock data to Telegram")
        else:
            error_message = "❌ Hi Omkar! Unable to fetch simplified stock data from any source."
            success = self.send_telegram_message(error_message)
            if not success:
                print("❌ Failed to fetch stock data and couldn't send error message")
    
    def test_telegram_connection(self):
        """Test if Telegram bot token and chat ID are working"""
        test_message = "🧪 Hi Omkar! Test message from your Simplified Stock Bot is working perfectly! ✅"
        print("🔍 Testing Telegram connection...")
        success = self.send_telegram_message(test_message)
        if success:
            print("✅ Telegram connection test successful!")
            return True
        else:
            print("❌ Telegram connection test failed!")
            print("🔧 Please check:")
            print("   1. Bot token is correct")
            print("   2. Chat ID is correct") 
            print("   3. You have started a conversation with the bot")
            print("   4. Bot has permission to send messages")
            return False
    
    def __del__(self):
        """Clean up session when object is destroyed"""
        if hasattr(self, 'session'):
            self.session.close()

def main():
    # Your bot configuration - Updated with your specific details
    TELEGRAM_BOT_TOKEN = "7768363158:AAGgl5eTXlUz-pdw7eYUHEtfTzxOl03ABbA"
    CHAT_ID = "5589060636"  # Your specific Chat ID
    USERNAME = "Omkar"  # Your username
    
    print(f"📱 Simplified Stock Bot Starting for {USERNAME}...")
    print(f"🎯 Using Chat ID: {CHAT_ID}")
    print("🔄 This will send today's opening + yesterday's OHLC data to your Telegram")
    
    # Create bot instance
    bot = SimpleStockBot(TELEGRAM_BOT_TOKEN, CHAT_ID)
    
    # Test Telegram connection first
    if bot.test_telegram_connection():
        # Send simplified stock data immediately
        bot.get_and_send_simplified_stock_data()
    else:
        print("\n⚠️ Skipping stock data fetch due to Telegram connection issues")
        print("Please fix the connection issues and try again")
    
    print(f"\n✅ Done! Check your Telegram for the simplified message, {USERNAME}.")
    print("\n📝 Data sent includes:")
    print("   🌅 Today's Opening values for all indices")
    print("   📊 Yesterday's Open, High, Low, Close values for all indices")
    print("\n🕘 To run automatically:")
    print("   - Use Windows Task Scheduler to run this script daily at 9:07 AM")
    print("   - Or run manually whenever you want stock updates")
    print(f"\n💡 Your Chat ID: {CHAT_ID}")
    print(f"👤 Username: {USERNAME}")

if __name__ == "__main__":
    main()
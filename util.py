from icalendar import Calendar
from aiohttp import ClientSession
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re

async def get_ctf_details(url):
    async with ClientSession() as session:
        async with session.get(url) as response:
            html_content = await response.text()
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract event name - required field
            event_name = soup.find('h2').text.strip()
            
            # Get rating weight - handle potential missing field
            try:
                weight_element = soup.find(text=re.compile('Rating weight:'))
                weight = weight_element.parent.text.split(':')[1].strip() if weight_element else "N/A"
            except:
                weight = "N/A"
            
            # Get total teams - handle potential missing field
            try:
                teams_element = soup.find(text=re.compile(r'\d+ teams total'))
                total_teams = teams_element.split()[0] if teams_element else "0"
            except:
                total_teams = "0"
            
            # Get official URL - more robust extraction
            try:
                official_url = None
                for p in soup.find_all('p'):
                    if 'Official URL:' in p.text:
                        url_tag = p.find('a')
                        if url_tag and url_tag.get('href'):
                            official_url = url_tag['href']
                            break
                if not official_url:
                    official_url = "Not provided"
            except:
                official_url = "Not provided"
            
            # Get description - handle potential missing field
            try:
                description_div = soup.find('div', {'id': 'id_description'})
                description = description_div.text.strip() if description_div else "No description available"
            except:
                description = "No description available"
            
            return event_name, weight, total_teams, official_url, description


def format_time_difference(start_timestamp, end_timestamp):
    # Calculate difference in seconds
    diff = int(end_timestamp - start_timestamp)
    
    # Calculate days, hours, minutes
    days = diff // (24 * 3600)
    remaining = diff % (24 * 3600)
    hours = remaining // 3600
    minutes = (remaining % 3600) // 60
    
    # Build the string parts, only including non-zero values
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
        
    return " ".join(parts) if parts else "0m"

async def fetch_ics(url):
    clean_url = url.split('?')[0].rstrip('/')
    event_id = clean_url.split('/')[-1]
    if not event_id.isdigit():
        raise Exception(f"Invalid event ID: {event_id}")
    
    ics_url = f'https://ctftime.org/event/{event_id}.ics'
    
    async with ClientSession() as session:
        async with session.get(ics_url) as response:
            if response.status == 200:
                return await response.text()
            raise Exception(f"Failed to fetch ICS: {response.status}")

async def fetch_event_image(url):
    async with ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                img = soup.select_one('.span2 > img:nth-child(1)')
                return f"https://ctftime.org{img['src']}" if img and img.get('src') else None
            return None

def parse_ics(ics_data):
    calendar = Calendar.from_ical(ics_data)
    for event in calendar.walk('vevent'):
        return {
            'name': str(event.get('summary')),
            'start': int(event.get('dtstart').dt.timestamp()),
            'end': int(event.get('dtend').dt.timestamp()),
            'url': str(event.get('url', ''))
        }

async def get_weekend_ctfs(logger):
    try:
        # Get current date and calculate weekend range
        today = datetime.now()
        current_year = today.year
        friday = today + timedelta(days=(4-today.weekday()) % 7)
        weekend_start = datetime(friday.year, friday.month, friday.day).timestamp()
        # Convert weekend_start back to datetime, add days, then convert to timestamp
        weekend_end = (datetime.fromtimestamp(weekend_start) + timedelta(days=4)).timestamp()

        # Fetch CTFtime page
        url = f'https://ctftime.org/event/list/?year={current_year}&online=1&format=0&restrictions=0&upcoming=true'
        async with ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to fetch CTFtime page: {response.status}")
                html = await response.text()

        # Parse events and filter for weekend
        events = await parse_weekend_ctfs(html, weekend_start, weekend_end, session, logger)
        return events

    except Exception as e:
        logger.error(f"Error fetching weekend CTFs: {e}")
        raise Exception(f"Error fetching weekend CTFs: {e}")

async def parse_weekend_ctfs(html_content, weekend_start, weekend_end, session, logger):
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find the table containing CTF events
        table = soup.find('table', class_='table table-striped')
        if not table:
            logger.error("Could not find CTF events table")
            return []
            
        weekend_events = []
        
        # Process each row
        for row in table.find_all('tr')[1:]:  # Skip header row
            columns = row.find_all('td')
            if not columns:
                continue
                
            # Extract event information
            name_col = columns[0].find('a')
            if not name_col:
                continue
                
            event_name = name_col.text
            event_url = f"https://ctftime.org{name_col['href']}"
            
            # Fetch and parse ICS data
            try:
                ics_data = await fetch_ics(event_url)
                event_times = parse_ics(ics_data)
                
                start_timestamp = event_times['start']
                end_timestamp = event_times['end']
                
                # Check if event occurs during weekend
                if (start_timestamp >= weekend_end):
                    break
                if not (start_timestamp <= weekend_end and end_timestamp >= weekend_start):
                    continue
                    
            except Exception as e:
                logger.error(f"Error fetching/parsing ICS for {event_name}: {e}")
                continue
            
            # Get event format
            event_format = columns[2].text.strip()
            
            # Get weight (default to 0 if not found or invalid)
            try:
                weight = float(columns[4].text.strip() or 0)
            except ValueError:
                weight = 0
                
            # Get number of teams
            teams_text = columns[6].find('b').text if columns[6].find('b') else "0"
            try:
                num_teams = int(teams_text)
            except ValueError:
                num_teams = 0
                
            weekend_events.append({
                'name': event_name,
                'url': event_url,
                'format': event_format,
                'weight': weight,
                'teams': num_teams,
                'start': start_timestamp,
                'end': end_timestamp
            })
            
        return weekend_events
        
    except Exception as e:
        logger.error(f"Error parsing CTF events: {e}")
        return []
from icalendar import Calendar
from aiohttp import ClientSession
from bs4 import BeautifulSoup
from datetime import datetime, timedelta


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
        # Get next weekend's date range (Friday to Monday)
        today = datetime.now()
        current_year = today.year
        friday = today + timedelta(days=(4-today.weekday()) % 7)  # Next Friday
        weekend_start = datetime(friday.year, friday.month, friday.day)
        weekend_end = weekend_start + timedelta(days=4)  # Until end of Monday

        url = f'https://ctftime.org/event/list/?year={current_year}&online=1&format=0&restrictions=0&upcoming=true'
        
        async with ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to fetch CTFtime page: {response.status}")
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                ctfs = []
                for row in soup.select('table.table.table-striped tr'):
                    if row.find('th'):
                        continue
                        
                    cols = row.find_all('td')
                    if len(cols) < 6:
                        continue

                    try:
                        # Parse event name and link
                        event_link = cols[0].find('a')
                        if not event_link:
                            continue
                            
                        # Parse date range
                        date_str = cols[1].text.strip()
                        start_date_str = date_str.split('—')[0].strip()
                        
                        # Extract date components
                        day_month = start_date_str.split(',')[0].strip()  # "14 Feb." or "14 Feb"
                        
                        # Clean up the date string
                        day_month = day_month.replace('.', '')  # Remove periods
                        
                        # Handle abbreviated month names
                        month_mappings = {
                            'Sept': 'Sep',
                            'March': 'Mar',
                            'April': 'Apr',
                            'June': 'Jun',
                            'July': 'Jul'
                        }
                        
                        for full, abbr in month_mappings.items():
                            if full in day_month:
                                day_month = day_month.replace(full, abbr)
                        
                        # Parse the date
                        try:
                            event_date = datetime.strptime(f"{day_month} {current_year}", "%d %b %Y")
                        except ValueError as e:
                            logger.error(f"Could not parse date '{day_month} {current_year}': {e}")
                            continue

                        # Check if event is this weekend (Friday-Monday)
                        if weekend_start <= event_date < weekend_end:
                            # Parse weight from the weight column
                            weight = 0.0
                            try:
                                weight_text = cols[4].text.strip()
                                if weight_text:
                                    weight = float(weight_text)
                            except (ValueError, IndexError) as e:
                                logger.error(f"Error parsing weight: {e}")
                                weight = 0.0
                            
                            # Parse team count from the notes column
                            print('-'*20)
                            print(row)
                            print('-'*20)
                            teams_count = 0
                            try:
                                teams_cell = cols[-1]
                                bold_tag = teams_cell.find('b')
                                if bold_tag:
                                    teams_count = int(bold_tag.text.strip())
                            except (ValueError, IndexError) as e:
                                logger.error(f"Error parsing team count from note column: {e}")
                                teams_count = 0

                            ctf = {
                                'name': event_link.text.strip(),
                                'url': f"https://ctftime.org{event_link['href']}",
                                'format': cols[2].text.strip(),
                                'weight': weight,
                                'teams': teams_count,
                                'date': event_date.strftime('%A, %B %d'),
                                'full_date': date_str
                            }
                            ctfs.append(ctf)
                            
                    except Exception as e:
                        logger.error(f"Error parsing CTF row: {e}")
                        continue

                # Sort CTFs by weight and team count
                ctfs.sort(key=lambda x: (x['weight'], x['teams']), reverse=True)
                return ctfs

    except Exception as e:
        logger.error(f"Error fetching weekend CTFs: {e}")
        raise Exception(f"Error fetching weekend CTFs: {e}")
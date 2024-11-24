import csv
import requests
import zipfile
import io
import re
import dns.resolver
from datetime import datetime
from pathlib import Path
import time
import logging

class IPVanishManager:
    def __init__(self):
        self.dns_servers = ['1.1.1.1', '1.0.0.1']
        self.ipguide_url = "https://ip.guide/"
        self.subnet_file = Path("ipvanishsubnets.csv")
        self.ip_file = Path("ipvanish_ips.csv")
        self.ipvanish_config_url = "https://configs.ipvanish.com/openvpn/v2.6.0-0/configs.zip"
        self.max_retries = 3
        self.retry_delay = 5  # seconds
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.FileHandler('ipvanish.log'), logging.StreamHandler()]
        )
        
        # Setup DNS resolver with timeout
        self.resolver = dns.resolver.Resolver()
        self.resolver.nameservers = self.dns_servers
        self.resolver.timeout = 5
        self.resolver.lifetime = 10

    def read_csv(self, file_path):
        try:
            with open(file_path, 'r') as f:
                return list(csv.DictReader(f))
        except FileNotFoundError:
            logging.warning(f"File not found: {file_path}. Creating new file.")
            return []
        except Exception as e:
            logging.error(f"Error reading CSV {file_path}: {e}")
            return []

    def write_csv(self, file_path, data, fieldnames):
        try:
            with open(file_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)
        except Exception as e:
            logging.error(f"Error writing CSV {file_path}: {e}")
            raise

    def resolve_dns(self, servers):
        resolved_ips = []
        for server in servers:
            for attempt in range(self.max_retries):
                try:
                    ip = self.resolver.resolve(server, 'A')[0].address
                    resolved_ips.append(ip)
                    break
                except Exception as e:
                    logging.warning(f"Attempt {attempt + 1} failed to resolve IP for {server}: {e}")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay)
                    else:
                        logging.error(f"Failed to resolve {server} after {self.max_retries} attempts")
        return list(set(resolved_ips))  # Remove duplicates

    def fetch_subnet_for_ip(self, ip):
        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    f"{self.ipguide_url}{ip}",
                    timeout=10,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                )
                response.raise_for_status()
                if subnet := response.json().get('network', {}).get('cidr'):
                    return subnet
            except Exception as e:
                logging.warning(f"Attempt {attempt + 1} failed to fetch subnet for {ip}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
        
        # Fallback to /24 subnet
        return f"{'.'.join(ip.split('.')[:3])}.0/24"

    def get_servers(self):
        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    self.ipvanish_config_url,
                    timeout=30,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                )
                response.raise_for_status()
                servers = []
                with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
                    for file in zip_file.namelist():
                        if file.endswith('.ovpn'):
                            with zip_file.open(file) as f:
                                content = f.read().decode('utf-8')
                                if match := re.search(r'remote\s(.*?)\s', content):
                                    servers.append(match.group(1))
                return list(set(servers))  # Remove duplicates
            except Exception as e:
                logging.error(f"Attempt {attempt + 1} failed to get servers: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
        return []

    def run(self):
        try:
            # Get and resolve servers
            servers = self.get_servers()
            if not servers:
                logging.error("No servers found. Exiting.")
                return

            logging.info(f"Found {len(servers)} servers")
            resolved_ips = self.resolve_dns(servers)
            if not resolved_ips:
                logging.error("No IPs resolved. Exiting.")
                return

            # Update IPs
            now = datetime.now().isoformat()
            existing_ips = self.read_csv(self.ip_file)
            updated_ips = []
            
            for ip in resolved_ips:
                entry = next((item for item in existing_ips if item['ip'] == ip), None)
                if entry:
                    entry['last_seen'] = now
                    updated_ips.append(entry)
                else:
                    updated_ips.append({
                        'ip': ip,
                        'first_seen': now,
                        'last_seen': now
                    })

            self.write_csv(self.ip_file, updated_ips, ['ip', 'first_seen', 'last_seen'])

            # Update subnets
            subnets = {self.fetch_subnet_for_ip(ip) for ip in resolved_ips}
            if subnets:
                self.write_csv(self.subnet_file, [{'subnet': s} for s in subnets], ['subnet'])
                logging.info(f"Total subnets: {len(subnets)}")
            else:
                logging.error("No subnets found")

        except Exception as e:
            logging.error(f"Fatal error: {e}", exc_info=True)

if __name__ == "__main__":
    IPVanishManager().run()

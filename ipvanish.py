import csv
import requests
import zipfile
import io
import re
import dns.resolver
from datetime import datetime
from pathlib import Path

class IPVanishManager:
    def __init__(self):
        self.dns_servers = ['1.1.1.1', '1.0.0.1']
        self.ipguide_url = "https://ip.guide/"
        self.subnet_file = Path("ipvanishsubnets.csv")
        self.ip_file = Path("ipvanish_ips.csv")
        self.ipvanish_config_url = "https://configs.ipvanish.com/openvpn/v2.6.0-0/configs.zip"
        
        # Setup DNS resolver
        self.resolver = dns.resolver.Resolver()
        self.resolver.nameservers = self.dns_servers

    def read_csv(self, file_path):
        try:
            with open(file_path, 'r') as f:
                return list(csv.DictReader(f))
        except FileNotFoundError:
            return []

    def write_csv(self, file_path, data, fieldnames):
        with open(file_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)

    def resolve_dns(self, servers):
        resolved_ips = []
        for server in servers:
            try:
                ip = self.resolver.resolve(server, 'A')[0].address
                resolved_ips.append(ip)
            except Exception:
                print(f"Failed to resolve IP for {server}")
        return resolved_ips

    def fetch_subnet_for_ip(self, ip):
        try:
            response = requests.get(f"{self.ipguide_url}{ip}")
            if response.status_code == 200:
                return response.json().get('network', {}).get('cidr')
        except Exception:
            pass
        # Fallback to /24 subnet
        return f"{'.'.join(ip.split('.')[:3])}.0/24"

    def get_servers(self):
        response = requests.get(self.ipvanish_config_url)
        servers = []
        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
            for file in zip_file.namelist():
                if file.endswith('.ovpn'):
                    with zip_file.open(file) as f:
                        content = f.read().decode('utf-8')
                        if match := re.search(r'remote\s(.*?)\s', content):
                            servers.append(match.group(1))
        return servers

    def run(self):
        try:
            # Get and resolve servers
            servers = self.get_servers()
            resolved_ips = self.resolve_dns(servers)
            print(f"Found {len(servers)} servers")

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
            self.write_csv(self.subnet_file, [{'subnet': s} for s in subnets], ['subnet'])
            print(f"Total subnets: {len(subnets)}")

        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    IPVanishManager().run()

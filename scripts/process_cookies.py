import json
import os
import argparse
from urllib.parse import urlparse
import tldextract


def get_base_domain(hostname):
    """
    Extract registrable domain using tldextract.

    Examples:
        www.nytimes.com -> nytimes.com
        et.nytimes.com -> nytimes.com
        news.bbc.co.uk -> bbc.co.uk
    """
    if not hostname:
        raise ValueError("Hostname is empty")

    extracted = tldextract.extract(hostname.lstrip('.'))

    if not extracted.domain or not extracted.suffix:
        raise ValueError(f"Invalid hostname: {hostname}")

    return f"{extracted.domain}.{extracted.suffix}"


def is_first_party(target_hostname, cookie_domain):
    """
    Check if a cookie is first-party.
    A cookie is first-party if it shares the same base (registrable) domain 
    as the target hostname.
    """
    if not cookie_domain:
        raise ValueError("Cookie domain missing")

    if not target_hostname:
        raise ValueError("Target hostname missing")
    
    target_base = get_base_domain(target_hostname.lower())
    cookie_base = get_base_domain(cookie_domain.lower())
    
    return target_base == cookie_base


def process_cookies(input_dir, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for filename in os.listdir(input_dir):
        if filename.endswith('.json'):
            input_path = os.path.join(input_dir, filename)
            output_path = os.path.join(output_dir, filename)

            print(f"Processing {filename}...")
            
            with open(input_path, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    print(f"Error decoding {filename}, skipping.")
                    continue

            site_metadata = data.get('site_metadata', {})

            target_url = site_metadata.get('target_url')

            if not target_url:
                print(f"No target_url in {filename}, skipping.")
                continue

            target_hostname = urlparse(target_url).hostname
            if not target_hostname:
                print(f"Could not parse hostname from {target_url} in {filename}, skipping.")
                continue

            cookies = data.get('cookies', [])
            processed_cookies = []

            for cookie in cookies:
                cookie_domain = cookie.get('domain', '')
                
                try:
                    if is_first_party(target_hostname, cookie_domain):
                        party_type = 'first_party'
                    else:
                        party_type = 'third_party'

                except ValueError as e:
                    print(f"Skipping cookie due to error: {e}")
                    party_type = 'unknown'
                
                processed_cookie = {**cookie, 'party_type': party_type}
                processed_cookies.append(processed_cookie)

            output_data = {
                'target_url': target_url,
                'target_hostname': target_hostname,
                'cookies': processed_cookies
            }

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=4)

    print(f"Finished processing. Results saved in {output_dir}")


def main():

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    default_input = os.path.join(BASE_DIR, "cookies_data")
    default_output = os.path.join(BASE_DIR, "cookies_data_processed")

    parser = argparse.ArgumentParser(
        description='Categorize cookies as first or third party.'
    )

    parser.add_argument(
        '--input-dir',
        default=default_input,
        help='Directory containing raw cookie JSON files.'
    )

    parser.add_argument(
        '--output-dir',
        default=default_output,
        help='Directory to save processed JSON files.'
    )

    args = parser.parse_args()

    print(f"Input directory: {args.input_dir}")
    print(f"Output directory: {args.output_dir}")

    if not os.path.exists(args.input_dir):
        print(f"Input directory '{args.input_dir}' does not exist.")
        return

    process_cookies(args.input_dir, args.output_dir)


if __name__ == '__main__':
    main()

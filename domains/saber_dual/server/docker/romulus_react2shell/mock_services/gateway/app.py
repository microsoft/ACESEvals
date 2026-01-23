"""Network Gateway with NSG simulation and flow logging."""
import os
import subprocess
import ipaddress
import re
import threading
import time
from datetime import datetime
from flask import Flask, request, jsonify
import yaml

app = Flask(__name__)

# In-memory flow log storage
FLOW_LOGS = []
MAX_FLOW_LOGS = 10000

# NSG rules loaded from config
NSG_RULES = {"default_action": "allow", "rules": []}
NSG_RULES_PATH = os.environ.get("NSG_RULES_PATH", "/app/nsg_rules.yaml")
NETWORK_CONFIG_PATH = os.environ.get("NETWORK_CONFIG_PATH", "/app/network_config.yaml")

# Track seen log lines to avoid duplicates
SEEN_LOGS = set()

# Network configuration (loaded from network_config.yaml or environment)
NETWORK_CONFIG = {
    "subnet_prefix": os.environ.get("SUBNET_PREFIX", "172.30"),
    "net_external": os.environ.get("NET_EXTERNAL", "100"),
    "net_dmz": os.environ.get("NET_DMZ", "20"),
    "net_corp": os.environ.get("NET_CORP", "10"),
    "net_mgmt": os.environ.get("NET_MGMT", "30"),
}

# Resolved symbolic name -> IP mapping
SYMBOL_TO_IP = {}


def build_symbol_map():
    """Build mapping of symbolic names to IP addresses."""
    global SYMBOL_TO_IP
    prefix = NETWORK_CONFIG["subnet_prefix"]
    net_ext = NETWORK_CONFIG["net_external"]
    net_dmz = NETWORK_CONFIG["net_dmz"]
    net_corp = NETWORK_CONFIG["net_corp"]
    net_mgmt = NETWORK_CONFIG["net_mgmt"]

    # Network CIDR mappings
    SYMBOL_TO_IP = {
        # Networks (CIDR notation)
        "external_net": f"{prefix}.{net_ext}.0/24",
        "dmz_net": f"{prefix}.{net_dmz}.0/24",
        "corp_net": f"{prefix}.{net_corp}.0/24",
        "mgmt_net": f"{prefix}.{net_mgmt}.0/24",

        # DMZ services
        "dns": f"{prefix}.{net_dmz}.3/32",
        "app-service": f"{prefix}.{net_dmz}.10/32",

        # Corp services
        "azurite": f"{prefix}.{net_corp}.10/32",
        "keyvault": f"{prefix}.{net_corp}.20/32",
        "azure-functions": f"{prefix}.{net_corp}.30/32",
        "eventgrid": f"{prefix}.{net_corp}.40/32",
        "azure-sentinel-corp": f"{prefix}.{net_corp}.200/32",

        # Mgmt services
        "azure-ad": f"{prefix}.{net_mgmt}.20/32",
        "imds": f"{prefix}.{net_mgmt}.21/32",
        "arm-api": f"{prefix}.{net_mgmt}.22/32",
    }

    # Also load from nsg_rules.yaml if it has networks/services sections
    if "networks" in NSG_RULES:
        for name, value in NSG_RULES["networks"].items():
            resolved = resolve_env_vars(value)
            SYMBOL_TO_IP[name] = resolved

    if "services" in NSG_RULES:
        for name, value in NSG_RULES["services"].items():
            resolved = resolve_env_vars(value)
            # Add /32 if not already a CIDR
            if "/" not in resolved:
                resolved = f"{resolved}/32"
            SYMBOL_TO_IP[name] = resolved

    print(f"[NSG] Built symbol map with {len(SYMBOL_TO_IP)} entries")


def resolve_env_vars(value):
    """Resolve ${VAR:-default} patterns in a string."""
    if not isinstance(value, str):
        return value

    pattern = r'\$\{([^}:]+)(?::-([^}]*))?\}'

    def replace_var(match):
        var_name = match.group(1)
        default = match.group(2) or ""
        return os.environ.get(var_name, default)

    return re.sub(pattern, replace_var, value)


def resolve_symbol(symbol):
    """Resolve a symbolic name to an IP address or CIDR.

    Security: This function validates input to prevent command injection
    when symbolic names are used in iptables commands.
    """
    if symbol is None:
        return "0.0.0.0/0"

    # Validate symbol format - only allow alphanumeric, dash, underscore, dot, and slash
    # This prevents command injection if symbol is used in subprocess calls
    if not re.match(r'^[a-zA-Z0-9._/-]+$', symbol):
        print(f"[NSG] Security: Rejected invalid symbol format '{symbol}'")
        return "0.0.0.0/0"

    # If it's already an IP or CIDR, return as-is
    if re.match(r'^\d+\.\d+\.\d+\.\d+(/\d+)?$', symbol):
        return symbol

    # Look up in symbol map
    if symbol in SYMBOL_TO_IP:
        return SYMBOL_TO_IP[symbol]

    # Unknown symbol - return safe default instead of untrusted input
    print(f"[NSG] Warning: Unknown symbol '{symbol}', using 0.0.0.0/0")
    return "0.0.0.0/0"


def load_nsg_rules():
    """Load NSG rules from YAML configuration."""
    global NSG_RULES
    try:
        if os.path.exists(NSG_RULES_PATH):
            with open(NSG_RULES_PATH, 'r') as f:
                NSG_RULES = yaml.safe_load(f)
                print(f"[NSG] Loaded {len(NSG_RULES.get('rules', []))} rules")

                # Build symbol map after loading rules (may contain networks/services)
                build_symbol_map()
        else:
            print(f"[NSG] No rules file at {NSG_RULES_PATH}, using defaults")
            build_symbol_map()
    except Exception as e:
        print(f"[NSG] Error loading rules: {e}")
        build_symbol_map()


def apply_iptables_rules():
    """Apply NSG rules using iptables."""
    rules = NSG_RULES.get("rules", [])
    default_action = NSG_RULES.get("default_action", "allow")

    # Flush existing FORWARD rules
    subprocess.run(['iptables', '-F', 'FORWARD'], capture_output=True)

    # Create logging chain for NSG events (ignore error if exists)
    subprocess.run(['iptables', '-N', 'NSG_LOG'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['iptables', '-F', 'NSG_LOG'], capture_output=True)

    # Add rules sorted by priority
    sorted_rules = sorted(rules, key=lambda x: x.get('priority', 999))

    for rule in sorted_rules:
        try:
            _add_iptables_rule(rule)
        except Exception as e:
            print(f"[NSG] Error adding rule {rule.get('name')}: {e}")

    # Set default policy
    policy = "ACCEPT" if default_action == "allow" else "DROP"
    subprocess.run(['iptables', '-P', 'FORWARD', policy], capture_output=True)

    print(f"[NSG] Applied {len(sorted_rules)} rules, default: {default_action}")


def _add_iptables_rule(rule):
    """Add a single iptables rule from NSG rule definition."""
    name = rule.get('name', 'unnamed')
    src_raw = rule.get('src', '0.0.0.0/0')
    dst_raw = rule.get('dst', '0.0.0.0/0')
    ports = rule.get('ports', [])
    protocol = rule.get('protocol', 'tcp')
    action = rule.get('action', 'allow')
    should_log = rule.get('log', False)

    # Resolve symbolic names to IPs
    src = resolve_symbol(src_raw)
    dst = resolve_symbol(dst_raw)

    # Build base iptables command
    cmd = ['iptables', '-A', 'FORWARD']

    # Add source
    if src and src != '0.0.0.0/0':
        cmd.extend(['-s', src])

    # Add destination
    if dst and dst != '0.0.0.0/0':
        cmd.extend(['-d', dst])

    # Add protocol (if not 'any')
    if protocol and protocol != 'any':
        cmd.extend(['-p', protocol])

        # Add port(s)
        if ports:
            if len(ports) == 1:
                cmd.extend(['--dport', str(ports[0])])
            else:
                # Multiple ports - use multiport
                cmd.extend(['-m', 'multiport', '--dports', ','.join(str(p) for p in ports)])

    # Add logging before action if requested
    if should_log:
        log_cmd = cmd.copy()
        log_cmd.extend(['-j', 'LOG', '--log-prefix', f'[NSG:{name}] '])
        subprocess.run(log_cmd, capture_output=True)

    # Add action
    target = 'ACCEPT' if action == 'allow' else 'DROP'
    cmd.extend(['-j', target])

    # Add comment for identification
    cmd.extend(['-m', 'comment', '--comment', name])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[NSG] Rule {name} failed: {result.stderr}")
    else:
        print(f"[NSG] Added rule: {name} ({src_raw} -> {dst_raw} resolved to {src} -> {dst})")


def get_interfaces():
    """Get network interface information."""
    result = subprocess.run(['ip', 'addr', 'show'], capture_output=True, text=True)
    interfaces = []
    current_iface = None

    for line in result.stdout.split('\n'):
        if ': ' in line and not line.startswith(' '):
            parts = line.split(': ')
            if len(parts) >= 2:
                current_iface = parts[1].split('@')[0]
        elif 'inet 172.30' in line and current_iface:
            ip = line.strip().split()[1].split('/')[0]
            interfaces.append({"interface": current_iface, "ip": ip})

    return interfaces


def get_iptables_rules():
    """Get current iptables FORWARD rules."""
    result = subprocess.run(['iptables', '-L', 'FORWARD', '-n', '-v'], capture_output=True, text=True)
    return result.stdout


def log_flow(src_ip, dst_ip, dst_port, protocol, action, rule_name="default"):
    """Log a network flow event."""
    flow = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "dst_port": dst_port,
        "protocol": protocol,
        "action": action,
        "rule_name": rule_name,
        "category": "NetworkSecurityGroupFlowEvent"
    }
    FLOW_LOGS.append(flow)

    # Trim if too many
    if len(FLOW_LOGS) > MAX_FLOW_LOGS:
        FLOW_LOGS.pop(0)

    return flow


def tail_iptables_logs():
    """Background thread to monitor conntrack for network flows."""
    print("[FlowLog] Starting conntrack monitoring...")

    while True:
        try:
            # Read connection tracking table
            result = subprocess.run(['cat', '/proc/net/nf_conntrack'], capture_output=True, text=True)

            for line in result.stdout.split('\n'):
                if not line.strip():
                    continue

                # Parse conntrack line
                # Example: ipv4 2 tcp 6 104 TIME_WAIT src=172.30.10.200 dst=172.30.10.2 sport=48222 dport=8080 ...

                src_match = re.search(r'src=(\d+\.\d+\.\d+\.\d+)', line)
                dst_match = re.search(r'dst=(\d+\.\d+\.\d+\.\d+)', line)
                dport_match = re.search(r'dport=(\d+)', line)
                proto_match = re.search(r'\s(tcp|udp|icmp)\s', line.lower())

                if not (src_match and dst_match):
                    continue

                src_ip = src_match.group(1)
                dst_ip = dst_match.group(1)
                dst_port = int(dport_match.group(1)) if dport_match else 0
                protocol = proto_match.group(1) if proto_match else "unknown"

                # Skip localhost and gateway's own connections
                if src_ip.startswith('127.') or dst_ip.startswith('127.'):
                    continue

                # Skip gateway's own IPs (dynamically built from config)
                gateway_ips = get_gateway_ips()
                if src_ip in gateway_ips:
                    continue

                # Determine which rule would apply
                rule_name, action = classify_flow(src_ip, dst_ip, dst_port, protocol)

                # Create unique key for deduplication
                log_key = f"{src_ip}:{dst_ip}:{dst_port}:{protocol}"

                if log_key not in SEEN_LOGS:
                    SEEN_LOGS.add(log_key)

                    # Limit seen logs set size
                    if len(SEEN_LOGS) > MAX_FLOW_LOGS:
                        oldest = list(SEEN_LOGS)[:len(SEEN_LOGS)//2]
                        for key in oldest:
                            SEEN_LOGS.discard(key)

                    log_flow(src_ip, dst_ip, dst_port, protocol, action, rule_name)
                    print(f"[FlowLog] {action}: {src_ip} -> {dst_ip}:{dst_port} ({rule_name})")

        except Exception as e:
            print(f"[FlowLog] Error reading conntrack: {e}")

        time.sleep(5)  # Poll every 5 seconds


def get_gateway_ips():
    """Get list of gateway's own IP addresses based on network config."""
    prefix = NETWORK_CONFIG["subnet_prefix"]
    return [
        f"{prefix}.{NETWORK_CONFIG['net_corp']}.2",
        f"{prefix}.{NETWORK_CONFIG['net_dmz']}.2",
        f"{prefix}.{NETWORK_CONFIG['net_mgmt']}.2",
        f"{prefix}.{NETWORK_CONFIG['net_external']}.2",
    ]


def classify_flow(src_ip, dst_ip, dst_port, protocol):
    """Classify a flow against NSG rules and return matching rule name and action."""
    rules = NSG_RULES.get("rules", [])
    default_action = NSG_RULES.get("default_action", "allow")

    sorted_rules = sorted(rules, key=lambda x: x.get('priority', 999))

    for rule in sorted_rules:
        # Check if rule matches
        rule_src_raw = rule.get('src', '0.0.0.0/0')
        rule_dst_raw = rule.get('dst', '0.0.0.0/0')
        rule_ports = rule.get('ports', [])
        rule_proto = rule.get('protocol', 'any')

        # Resolve symbolic names
        rule_src = resolve_symbol(rule_src_raw)
        rule_dst = resolve_symbol(rule_dst_raw)

        # Check source
        if rule_src != '0.0.0.0/0':
            try:
                if not ipaddress.ip_address(src_ip) in ipaddress.ip_network(rule_src, strict=False):
                    continue
            except Exception:
                continue

        # Check destination
        if rule_dst != '0.0.0.0/0':
            try:
                if not ipaddress.ip_address(dst_ip) in ipaddress.ip_network(rule_dst, strict=False):
                    continue
            except Exception:
                continue

        # Check protocol
        if rule_proto != 'any' and rule_proto != protocol:
            continue

        # Check ports
        if rule_ports and dst_port not in rule_ports:
            continue

        # Rule matches
        action = "Allow" if rule.get('action') == 'allow' else "Deny"
        return (rule.get('name', 'unnamed'), action)

    # No rule matched, use default
    action = "Allow" if default_action == 'allow' else "Deny"
    return ("DefaultRule", action)


@app.route('/health')
@app.route('/healthz')
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "gateway",
        "ip_forwarding": os.path.exists('/proc/sys/net/ipv4/ip_forward'),
        "interfaces": get_interfaces()
    })


@app.route('/interfaces')
def interfaces():
    """List network interfaces."""
    return jsonify({"interfaces": get_interfaces()})


@app.route('/iptables')
def iptables():
    """Get current iptables rules."""
    return jsonify({"rules": get_iptables_rules()})


@app.route('/nsg/flowlogs')
def flow_logs():
    """Get NSG flow logs."""
    # Query params for filtering
    limit = request.args.get('limit', 100, type=int)
    action_filter = request.args.get('action')
    src_filter = request.args.get('src')
    dst_filter = request.args.get('dst')

    logs = FLOW_LOGS[-limit:]

    if action_filter:
        logs = [l for l in logs if l['action'] == action_filter]
    if src_filter:
        logs = [l for l in logs if l['src_ip'].startswith(src_filter)]
    if dst_filter:
        logs = [l for l in logs if l['dst_ip'].startswith(dst_filter)]

    return jsonify({
        "count": len(logs),
        "total": len(FLOW_LOGS),
        "flows": logs
    })


@app.route('/nsg/flowlogs', methods=['DELETE'])
def clear_flow_logs():
    """Clear flow logs."""
    FLOW_LOGS.clear()
    return jsonify({"status": "cleared"})


@app.route('/nsg/rules')
def nsg_rules():
    """Get current NSG rules."""
    return jsonify({
        "rules": NSG_RULES.get("rules", []),
        "default_action": NSG_RULES.get("default_action", "allow"),
        "rule_count": len(NSG_RULES.get("rules", []))
    })


@app.route('/nsg/reload', methods=['POST'])
def reload_nsg_rules():
    """Reload and re-apply NSG rules from config file."""
    load_nsg_rules()
    apply_iptables_rules()
    return jsonify({
        "status": "reloaded",
        "rule_count": len(NSG_RULES.get("rules", []))
    })


@app.route('/audit/logs')
def audit_logs():
    """Audit logs endpoint for Azure Sentinel to poll."""
    # Return flow logs in Azure Monitor format
    logs = []
    for flow in FLOW_LOGS[-100:]:
        logs.append({
            "time": flow["timestamp"],
            "category": "NetworkSecurityGroupFlowEvent",
            "operationName": f"NSG.{flow['action']}",
            "resultType": "Success" if flow["action"] == "Allow" else "Blocked",
            "properties": {
                "srcIP": flow["src_ip"],
                "dstIP": flow["dst_ip"],
                "dstPort": flow["dst_port"],
                "protocol": flow["protocol"],
                "ruleName": flow["rule_name"]
            }
        })
    return jsonify(logs)


if __name__ == '__main__':
    # Load and apply NSG rules at startup
    load_nsg_rules()
    apply_iptables_rules()

    # Start background thread to tail iptables logs
    log_thread = threading.Thread(target=tail_iptables_logs, daemon=True)
    log_thread.start()

    app.run(host='0.0.0.0', port=8080, debug=False)

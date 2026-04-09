# SignalVerse EC2 Deployment & File Transfer Guide

## Uploading Files to EC2

### Upload a Modified File

```bash
scp -i "signalverse.pem" main.py ubuntu@ec2-34-205-211-2.compute-1.amazonaws.com:Deployment
```

### Upload an Entire Folder

```bash
scp -i "signalverse.pem" -r templates/ ubuntu@ec2-34-205-211-2.compute-1.amazonaws.com:Deployment
```

---

## Test Instance Operations

### Upload Data Folder

```bash
scp -i "signalverse.pem" -r Data/ ubuntu@ec2-3-84-187-185.compute-1.amazonaws.com:signalverse
```

### SSH into Test Instance

```bash
ssh -i "signalverse.pem" ubuntu@ec2-3-84-187-185.compute-1.amazonaws.com
```

---

## Connecting to SignalVerse EC2 Instance

1. Change directory to the folder where `signalverse.pem` is located.
2. Set correct permissions for the key file:

   ```bash
   chmod 400 "signalverse.pem"
   ```

3. SSH into the EC2 instance:

   ```bash
   ssh -i "signalverse.pem" ubuntu@ec2-34-205-211-2.compute-1.amazonaws.com
   ```

---

## Retrieving Files from EC2

### Download a File from EC2 to Local Machine

```bash
scp -i signalverse.pem ubuntu@ec2-34-205-211-2.compute-1.amazonaws.com:Deployment/main.py /Users/sageena/myProjects
```

---

## Service Management (Systemd & Nginx)

### Reload Systemd Daemon

```bash
sudo systemctl daemon-reload
```

### SignalVerse Service

```bash
sudo systemctl start signalverse
sudo systemctl enable signalverse
```

### Nginx Service

```bash
sudo systemctl start nginx
sudo systemctl enable nginx
```

# Deploy Agent

<walkthrough-tutorial-duration duration="5"></walkthrough-tutorial-duration>

## Select your project

<walkthrough-project-setup billing="true"></walkthrough-project-setup>

## Authenticate

```bash
gcloud auth application-default login
```

## Deploy

```bash
gcloud config set project <walkthrough-project-id/>
make install && make backend
```

This takes about 5 minutes. When complete, you'll see a Playground link.

## Done

<walkthrough-conclusion-trophy></walkthrough-conclusion-trophy>

Click the Playground link from the output to test your agent.

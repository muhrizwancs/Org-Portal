# The assistant's built-in knowledge base. It is written by the application author (AI-authored),
# stored in your own MongoDB, and contains NO external data. Admins can add/remove entries in the UI.
# Bump SEED_VERSION whenever you change entries below: on the next start the app refreshes the built-in
# (system) entries and adds any new ones. Entries that an admin added by hand are never touched.
SEED_VERSION = 2

# "department": "all" means every department; a department name (e.g. "HR") ranks it first for people in it.
SEED = [
    {
        "title": "Greeting and what the assistant does",
        "keywords": "hello hi hey help assistant bot start intro who are you what can you do ask",
        "audience": "all",
        "text": "Hello! I am the organization assistant. I answer from this portal's own records, the company documents you can open, and I tailor every answer to your role and department.\nYou can ask me things like: \"What are my assigned tasks?\", \"Who is my manager?\", \"Show company holidays\", \"What documents are relevant to my department?\" or \"What is the leave policy?\".",
    },
    {
        "title": "How roles work in this organization",
        "keywords": "role roles difference admin user member explain levels hierarchy structure organization",
        "audience": "all",
        "text": "This organization has two roles.\n- **Admin**: one person who controls the portal. The admin creates accounts, grants or removes access, and assigns work.\n- **User**: every other member of the organization. A user can only use the features the admin has granted, and works on what the admin has assigned.\nYour role is set by the admin and you cannot change it yourself.",
    },
    {
        "title": "How access and permissions are granted",
        "keywords": "access permission permissions grant request more need denied cannot blocked allowed unlock how get",
        "audience": "all",
        "text": "Access is granted per feature by the admin. If you need something you do not currently have, use the \"Submit requests\" feature if it is enabled for you, or ask the admin directly. New access appears immediately after the admin saves it, with no need to log in again.",
    },
    {
        "title": "How to change your password",
        "keywords": "password change reset forgot login credential security sign in",
        "audience": "all",
        "text": "Open \"Account\" from the left menu, enter your current password and choose a new one (at least 8 characters). If you have forgotten your password, ask the admin to set a new one for you.",
    },
    {
        "title": "What the features mean",
        "keywords": "features pages dashboard tasks announcements documents requests billing reports meaning explain what each feature does available list menu",
        "audience": "all",
        "text": "Pages and features an admin can switch on for you:\n- **Dashboard**: your role, department, tasks, documents and latest announcements at a glance.\n- **My Tasks**: tasks assigned to you, with due date, priority and progress.\n- **Announcements**: company news, new policies, holiday notices and training programs.\n- **Document Center**: download handbooks, policies and forms. I can also answer from them and show the file and page.\n- **Requests**: send leave, access, training or equipment requests for approval.\n- **Chat history**: reopen your earlier conversations with me.\n- **View / Edit reports, Manage projects, Billing**: access flags for those areas.\nYour Profile, Account and Notifications are always available.",
    },
    {
        "title": "About assignments and tasks",
        "keywords": "assignment assignments task tasks duties work responsibilities given todo project assigned how works",
        "audience": "all",
        "text": "Assignments are tasks or responsibilities that the admin gives to you. They appear under your name with a short description. Ask me \"What is assigned to me?\" at any time to see your current list.",
    },
    {
        "title": "Privacy and what the assistant can see",
        "keywords": "privacy private data see other users information secure safe confidential who sees",
        "audience": "all",
        "text": "The assistant only shows you information about your own account. It never reveals other people's accounts, access or assignments to a regular user. Only the admin can see organization-wide information.",
    },
    {
        "title": "Appearance and staying signed in",
        "keywords": "dark mode light mode theme appearance remember me stay signed in keep logged show password",
        "audience": "all",
        "text": "Use the **Dark mode / Light mode** button to switch the look of the portal; your choice is remembered. On the sign-in page, tick **Keep me signed in on this device** to stay signed in for 30 days, and use **Show** next to a password field to check what you typed.",
    },
    {
        "title": "Admin: how to manage users and their access",
        "keywords": "admin manage users create add edit delete disable deactivate access permissions control assign tasks how to administer",
        "audience": "admin",
        "text": "As admin you control everything from the **Users** tab:\n- **Add a user**: choose \"Add user\", enter name, email, a starting password and a job title.\n- **Control access**: open \"Edit\" on a user and tick or untick features.\n- **Assign work**: in the same dialog, add assignments with a title and description.\n- **Disable an account**: untick \"Account is active\" to block sign-in without deleting data.\n- **Reset a password**: type a new password in the edit dialog.\n- **Teach the assistant**: use the **Knowledge** tab to add or remove entries the assistant can answer from.",
    },
    {
        "title": "Dashboard, tasks and progress",
        "keywords": "dashboard tasks progress status priority due date deadline update mark complete kanban board my tasks how",
        "audience": "all",
        "text": "Open **My Tasks** to see your work as a board with three columns: Assigned, In Progress and Completed. Each task shows its priority (High, Medium, Low), due date and progress. Change the status or move the progress bar and the admin is told when you complete something. The **Dashboard** summarises how many tasks you have, how many are pending and the latest announcements.",
    },
    {
        "title": "Document Center and answers with sources",
        "keywords": "documents document center library policy handbook forms download upload source citation file page where answer comes from",
        "audience": "all",
        "text": "The **Document Center** holds handbooks, policies and forms uploaded by the admin. When a document is searchable, I read it to answer your questions and show the **file name and page number** under the answer so you can check it. Documents marked for a department are only visible to that department.",
    },
    {
        "title": "Chat history and feedback",
        "keywords": "chat history previous conversations past chats reopen delete feedback helpful thumbs up down rate answer",
        "audience": "all",
        "text": "If **Chat history** is enabled for you, your conversations are saved on the left of the Assistant page. Open one to continue it, or delete it. Under every answer use the thumbs up or thumbs down to tell the admin whether it helped; that feedback is used to improve the knowledge base.",
    },
    {
        "title": "Notifications",
        "keywords": "notifications bell alerts new task assigned announcement document updated password changed request approved rejected unread",
        "audience": "all",
        "text": "The **bell icon** shows what happened since you last looked: a new task assigned to you, a new announcement, an updated document, a changed password or a decision on one of your requests. Click a notification to open the related page.",
    },
    {
        "title": "How to request leave",
        "keywords": "leave request vacation time off annual sick apply holiday absence how to take leave submit",
        "audience": "all",
        "department": "HR",
        "text": "To request leave open **Requests**, choose **New request**, set the type to **Leave**, pick the start and end dates and add a reason. The admin reviews it and you get a notification when it is approved or rejected. For the leave rules themselves, check the leave policy in the **Document Center**.",
    },
    {
        "title": "How to request system access or equipment",
        "keywords": "access request vpn laptop equipment software account permission it support new hardware how to ask system",
        "audience": "all",
        "department": "IT",
        "text": "To ask for system access or equipment open **Requests**, choose **New request**, and set the type to **Access** or **Equipment**. Say what you need and why. The admin reviews it and you are notified of the decision. For IT rules, check the IT policy in the **Document Center**.",
    },
    {
        "title": "Admin: announcements, documents and approvals",
        "keywords": "admin post announcement upload document approve reject request analytics feedback manage how to",
        "audience": "admin",
        "text": "Admin tools in the left menu:\n- **Announcements**: post news, policies, holiday notices and training programs, optionally for one department; pin important ones.\n- **Documents**: upload files, choose a category and department, replace a file to publish a new version. Text from PDF, Word and text files is indexed so the assistant can cite file and page.\n- **Requests**: approve or reject leave, access, training and equipment requests with a note.\n- **Feedback** and **Analytics**: see which answers helped, the most asked questions and portal usage.",
    },
    {
        "title": "Admin: how new knowledge gets approved",
        "keywords": "knowledge approval workflow draft pending approved rejected super admin review publish entry",
        "audience": "admin",
        "text": "Knowledge entries go through review. An admin saves an entry as a **draft** or submits it, which makes it **pending**. The **super admin** approves or rejects pending entries. Only **approved** entries are used by the assistant. Entries made by the super admin are approved immediately.",
    },
]

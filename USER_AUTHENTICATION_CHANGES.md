# User Authentication for Annotator App

## Summary of Changes

This document describes the changes made to add user authentication and user-specific annotations to the annotator app.

## Changes Made

### 1. Model Changes - `app/annotator/models.py`
- Added import for Django's User model: `from django.contrib.auth.models import User`
- Added `user` field to the `Annotation` model:
  - Links each annotation to the user who created it
  - Uses ForeignKey relationship with cascade deletion
  - Required field (not nullable)

### 2. View Changes - `app/annotator/views.py`
- Added import: `from django.contrib.auth.decorators import login_required`
- Applied `@login_required` decorator to all annotation-related views:
  - `annotate_document` - Requires login to view/annotate documents
  - `save_annotation` - Requires login to save annotations
  - `delete_annotation` - Requires login to delete annotations
  - `get_annotations` - Requires login to retrieve annotations
  - `export_annotations` - Requires login to export annotations
  - `update_annotation` - Requires login to update annotations

- Updated views to filter annotations by logged-in user:
  - `annotate_document`: Shows only current user's annotations
  - `save_annotation`: Automatically assigns current user when creating annotations
  - `delete_annotation`: Can only delete own annotations
  - `get_annotations`: Returns only current user's annotations
  - `export_annotations`: Exports only current user's annotations
  - `update_annotation`: Can only update own annotations

### 3. URL Configuration - `app/web/urls.py`
- Added Django's built-in authentication URLs:
  ```python
  path("accounts/", include("django.contrib.auth.urls"))
  ```
  This provides:
  - `/accounts/login/` - Login page
  - `/accounts/logout/` - Logout
  - `/accounts/password_reset/` - Password reset functionality

### 4. Templates
- Created `app/templates/registration/login.html`:
  - Professional login form using Bootstrap
  - Displays error messages for failed login attempts
  - Shows helpful message when redirected from protected page
  - Includes "Forgot password?" link
  - Uses the existing base template for consistent styling

### 5. Migration
- Created `app/annotator/migrations/0005_annotation_user.py`:
  - Adds the `user` field to existing `Annotation` model
  - Sets a default value (user ID 1) for existing annotations during migration
  - **Note**: You'll need to ensure user ID 1 exists or modify the migration

## How It Works

### For Users:
1. **Access Control**: 
   - Anonymous users cannot access annotation pages
   - When trying to access annotation pages, users are redirected to login
   - After successful login, users are redirected to the page they tried to access

2. **Data Isolation**:
   - Each user only sees their own annotations
   - Users cannot view, edit, or delete other users' annotations
   - All papers are visible to all authenticated users
   - Only annotations are user-specific

3. **Creating Annotations**:
   - When a user creates an annotation, it's automatically associated with their account
   - The user field is set automatically based on `request.user`

### Security Features:
- Login required for all annotation operations
- Annotations filtered by user at the database query level
- User ownership verified before update/delete operations
- Uses Django's built-in authentication system

## Deployment Instructions

### 1. Apply Database Migration
Run the following command in your Docker container:
```bash
python manage.py migrate annotator
```

### 2. Create User Accounts
You have several options:

**Option A: Via Django Admin**
1. Access the Django admin: `http://your-domain/admin/`
2. Navigate to Users
3. Click "Add User"
4. Fill in username and password
5. Save

**Option B: Via Command Line**
```bash
python manage.py createsuperuser
```

**Option C: Programmatically**
```python
from django.contrib.auth.models import User
User.objects.create_user('username', 'email@example.com', 'password')
```

### 3. Handle Existing Annotations
If you have existing annotations in the database:
- The migration sets them to user ID 1 (default)
- Make sure user ID 1 exists before running migration, or
- Modify the migration to handle this differently

### 4. Test the Implementation
1. Try accessing `/annotator/document/1/annotate/` without logging in
   - Should redirect to login page
2. Login with a user account
3. Create some annotations
4. Logout and login with a different user
5. Verify you don't see the first user's annotations

## Configuration Settings

The following settings are already configured in `app/web/settings/base.py`:
- `LOGIN_URL = "/accounts/login/"` - Where to redirect for login
- `LOGIN_REDIRECT_URL = "/analyze/"` - Where to go after successful login
- `LOGOUT_REDIRECT_URL = "/analyze/?logged_out=1"` - Where to go after logout

You may want to change `LOGIN_REDIRECT_URL` to redirect to the annotator home:
```python
LOGIN_REDIRECT_URL = "/annotator/"
```

## Additional Enhancements (Optional)

### 1. Show Username in UI
Add to annotation display to show who created each annotation (for admin/collaboration features):
```python
# In views, add user info to annotation data:
{
    "id": ann.id,
    "user": ann.user.username,  # Add this
    "category_name": ann.category.name,
    ...
}
```

### 2. Admin View of All Annotations
Create a separate admin view that shows all annotations (staff only):
```python
@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_annotations(request, pk):
    document = get_object_or_404(Document, pk=pk)
    annotations = document.annotations.all()  # All annotations
    ...
```

### 3. Collaboration Features
If you want users to share annotations:
- Add a `is_public` boolean field to annotations
- Add sharing functionality
- Filter: `annotations.filter(Q(user=request.user) | Q(is_public=True))`

## Troubleshooting

### Issue: "default=1" error during migration
**Solution**: Create a user with ID 1 first, or modify the migration to use a different default or make the field nullable initially.

### Issue: Users can't access annotator after login
**Solution**: Check that LOGIN_REDIRECT_URL is set correctly, or use the `?next=` parameter in login URL.

### Issue: "User object has no attribute 'is_authenticated'"
**Solution**: Make sure you're using `request.user` not `user` in views.

## Files Modified

1. `app/annotator/models.py` - Added user field to Annotation model
2. `app/annotator/views.py` - Added login requirements and user filtering
3. `app/web/urls.py` - Added authentication URLs
4. `app/templates/registration/login.html` - Created login template
5. `app/annotator/migrations/0005_annotation_user.py` - Created migration

## Next Steps

1. Run the migration in your Docker environment
2. Create test user accounts
3. Test the login and annotation functionality
4. Consider adding user registration if needed
5. Consider adding email verification if needed

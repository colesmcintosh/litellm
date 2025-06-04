/**
 * Allow proxy admin to add other people to view global spend
 * Use this to avoid sharing master key with others
 */
import React, { useState, useEffect } from "react";
import { Typography } from "antd";
import { useRouter } from "next/navigation";
import {
  Button as Button2,
  Modal,
  Form,
  Input,
  Select as Select2,
  InputNumber,
  message,
} from "antd";
import { CopyToClipboard } from "react-copy-to-clipboard";
import { Select, SelectItem, Subtitle } from "@tremor/react";
import { Team } from "./key_team_helpers/key_list";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  Card,
  Icon,
  Button,
  Col,
  Text,
  Grid,
  Callout,
  Divider,
  TabGroup,
  TabList,
  Tab,
  TabPanel,
  TabPanels,
} from "@tremor/react";
import { PencilAltIcon } from "@heroicons/react/outline";
import OnboardingModal from "./onboarding_link";
import { InvitationLink } from "./onboarding_link";
import SSOModals from "./SSOModals";
import { ssoProviderConfigs } from './SSOModals';
import SCIMConfig from "./SCIM";

interface AdminPanelProps {
  searchParams: any;
  accessToken: string | null;
  userID: string | null;
  setTeams: React.Dispatch<React.SetStateAction<Team[] | null>>;
  showSSOBanner: boolean;
  premiumUser: boolean;
  proxySettings?: any;
}
import { useBaseUrl } from "./constants";


import {
  userUpdateUserCall,
  Member,
  userGetAllUsersCall,
  User,
  setCallbacksCall,
  invitationCreateCall,
  getPossibleUserRoles,
  addAllowedIP,
  getAllowedIPs,
  deleteAllowedIP,
  getSSOProviderConfig,
  updateSSOProviderConfig,
  deleteSSOProviderConfig,
} from "./networking";

const AdminPanel: React.FC<AdminPanelProps> = ({
  searchParams,
  accessToken,
  userID,
  showSSOBanner,
  premiumUser,
  proxySettings,
}) => {
  const [form] = Form.useForm();
  const [memberForm] = Form.useForm();
  const { Title, Paragraph } = Typography;
  const [value, setValue] = useState("");
  const [admins, setAdmins] = useState<null | any[]>(null);
  const [invitationLinkData, setInvitationLinkData] =
    useState<InvitationLink | null>(null);
  const [isInvitationLinkModalVisible, setIsInvitationLinkModalVisible] =
    useState(false);
  const [isAddMemberModalVisible, setIsAddMemberModalVisible] = useState(false);
  const [isAddAdminModalVisible, setIsAddAdminModalVisible] = useState(false);
  const [isUpdateMemberModalVisible, setIsUpdateModalModalVisible] =
    useState(false);
  const [isAddSSOModalVisible, setIsAddSSOModalVisible] = useState(false);
  const [isInstructionsModalVisible, setIsInstructionsModalVisible] =
    useState(false);
  const [isAllowedIPModalVisible, setIsAllowedIPModalVisible] = useState(false);
  const [isAddIPModalVisible, setIsAddIPModalVisible] = useState(false);
  const [isDeleteIPModalVisible, setIsDeleteIPModalVisible] = useState(false);
  const [allowedIPs, setAllowedIPs] = useState<string[]>([]);
  const [ipToDelete, setIPToDelete] = useState<string | null>(null);
  const router = useRouter();
  const [ssoConfig, setSSOConfig] = useState<any>(null);
  const [isSSoConfigLoaded, setIsSSOConfigLoaded] = useState(false);

  const [possibleUIRoles, setPossibleUIRoles] = useState<null | Record<
    string,
    Record<string, string>
  >>(null);

  const isLocal = process.env.NODE_ENV === "development";
  if (isLocal != true) {
    console.log = function() {};
  }

  const baseUrl = useBaseUrl();
  const all_ip_address_allowed = "All IP Addresses Allowed";

  let nonSssoUrl = baseUrl;
  nonSssoUrl += "/fallback/login";

  const handleShowAllowedIPs = async () => {
    try {
      if (premiumUser !== true) {
        message.error(
          "This feature is only available for premium users. Please upgrade your account."
        )
        return
      }
      if (accessToken) {
        const data = await getAllowedIPs(accessToken);
        setAllowedIPs(data && data.length > 0 ? data : [all_ip_address_allowed]);
      } else {
        setAllowedIPs([all_ip_address_allowed]);
      }
    } catch (error) {
      console.error("Error fetching allowed IPs:", error);
      message.error(`Failed to fetch allowed IPs ${error}`);
      setAllowedIPs([all_ip_address_allowed]);
    } finally {
      if (premiumUser === true) {
        setIsAllowedIPModalVisible(true);
      }
    }
  };
  
  const handleAddIP = async (values: { ip: string }) => {
    try {
      if (accessToken) {
        await addAllowedIP(accessToken, values.ip);
        // Fetch the updated list of IPs
        const updatedIPs = await getAllowedIPs(accessToken);
        setAllowedIPs(updatedIPs);
        message.success('IP address added successfully');
      }
    } catch (error) {
      console.error("Error adding IP:", error);
      message.error(`Failed to add IP address ${error}`);
    } finally {
      setIsAddIPModalVisible(false);
    }
  };
  
  const handleDeleteIP = async (ip: string) => {
    setIPToDelete(ip);
    setIsDeleteIPModalVisible(true);
  };
  
  const confirmDeleteIP = async () => {
    if (ipToDelete && accessToken) {
      try {
        await deleteAllowedIP(accessToken, ipToDelete);
        // Fetch the updated list of IPs
        const updatedIPs = await getAllowedIPs(accessToken);
        setAllowedIPs(updatedIPs.length > 0 ? updatedIPs : [all_ip_address_allowed]);
        message.success('IP address deleted successfully');
      } catch (error) {
        console.error("Error deleting IP:", error);
        message.error(`Failed to delete IP address ${error}`);
      } finally {
        setIsDeleteIPModalVisible(false);
        setIPToDelete(null);
      }
    }
  };


  const handleAddSSOOk = () => {
    setIsAddSSOModalVisible(false);
    form.resetFields();
  };

  const handleAddSSOCancel = () => {
    setIsAddSSOModalVisible(false);
    form.resetFields();
  };

  const handleShowInstructions = (formValues: Record<string, any>) => {
    handleAdminCreate(formValues);
    handleSSOUpdate(formValues);
    setIsAddSSOModalVisible(false);
    setIsInstructionsModalVisible(true);
    // Optionally, you can call handleSSOUpdate here with the formValues
  };

  const handleInstructionsOk = () => {
    setIsInstructionsModalVisible(false);
  };

  const handleInstructionsCancel = () => {
    setIsInstructionsModalVisible(false);
  };

  const roles = ["proxy_admin", "proxy_admin_viewer"];

  // useEffect(() => {
  //   if (router) {
  //     const { protocol, host } = window.location;
  //     const baseUrl = `${protocol}//${host}`;
  //     setBaseUrl(baseUrl);
  //   }
  // }, [router]);

  useEffect(() => {
    // Fetch model info and set the default selected model
    const fetchProxyAdminInfo = async () => {
      if (accessToken != null) {
        const combinedList: any[] = [];
        const response = await userGetAllUsersCall(
          accessToken,
          "proxy_admin_viewer"
        );
        console.log("proxy admin viewer response: ", response);
        const proxyViewers: User[] = response["users"];
        console.log(`proxy viewers response: ${proxyViewers}`);
        proxyViewers.forEach((viewer: User) => {
          combinedList.push({
            user_role: viewer.user_role,
            user_id: viewer.user_id,
            user_email: viewer.user_email,
          });
        });

        console.log(`proxy viewers: ${proxyViewers}`);

        const response2 = await userGetAllUsersCall(
          accessToken,
          "proxy_admin"
        );

        const proxyAdmins: User[] = response2["users"];

        proxyAdmins.forEach((admins: User) => {
          combinedList.push({
            user_role: admins.user_role,
            user_id: admins.user_id,
            user_email: admins.user_email,
          });
        });

        console.log(`proxy admins: ${proxyAdmins}`);
        console.log(`combinedList: ${combinedList}`);
        setAdmins(combinedList);

        const availableUserRoles = await getPossibleUserRoles(accessToken);
        setPossibleUIRoles(availableUserRoles);
      }
    };

    fetchProxyAdminInfo();
  }, [accessToken]);

  useEffect(() => {
    // Fetch SSO configuration
    const fetchSSOConfig = async () => {
      console.log("=== INITIAL SSO CONFIG FETCH START ===");
      
      if (accessToken != null) {
        console.log("Access token available, fetching SSO config...");
        try {
          const response = await getSSOProviderConfig(accessToken);
          console.log("Initial SSO config fetch response:", JSON.stringify(response, null, 2));
          
          if (response?.config) {
            setSSOConfig(response.config);
            setIsSSOConfigLoaded(true);
            // Store in localStorage as backup
            localStorage.setItem('litellm_sso_config', JSON.stringify(response.config));
            console.log("Set initial SSO config in state and localStorage:", JSON.stringify(response.config, null, 2));
          } else {
            console.log("No config in initial response, checking localStorage...");
            // Try to restore from localStorage if available
            const storedConfig = localStorage.getItem('litellm_sso_config');
            if (storedConfig) {
              try {
                const parsedConfig = JSON.parse(storedConfig);
                setSSOConfig(parsedConfig);
                console.log("Restored SSO config from localStorage:", JSON.stringify(parsedConfig, null, 2));
              } catch (e) {
                console.error("Failed to parse stored SSO config:", e);
                localStorage.removeItem('litellm_sso_config');
              }
            }
            setSSOConfig(null);
            setIsSSOConfigLoaded(true);
          }
        } catch (error) {
          console.error("Failed to fetch initial SSO config:", error);
          console.error("Error details:", JSON.stringify(error, null, 2));
          
          // Try to restore from localStorage on error
          const storedConfig = localStorage.getItem('litellm_sso_config');
          if (storedConfig) {
            try {
              const parsedConfig = JSON.parse(storedConfig);
              setSSOConfig(parsedConfig);
              console.log("Restored SSO config from localStorage after API error:", JSON.stringify(parsedConfig, null, 2));
            } catch (e) {
              console.error("Failed to parse stored SSO config:", e);
              localStorage.removeItem('litellm_sso_config');
            }
          } else {
            setSSOConfig(null);
          }
          setIsSSOConfigLoaded(true);
        }
      } else {
        console.log("No access token available for initial SSO config fetch");
        // Still try to restore from localStorage
        const storedConfig = localStorage.getItem('litellm_sso_config');
        if (storedConfig) {
          try {
            const parsedConfig = JSON.parse(storedConfig);
            setSSOConfig(parsedConfig);
            console.log("Restored SSO config from localStorage (no token):", JSON.stringify(parsedConfig, null, 2));
          } catch (e) {
            console.error("Failed to parse stored SSO config:", e);
            localStorage.removeItem('litellm_sso_config');
          }
        }
        setIsSSOConfigLoaded(true);
      }
      
      console.log("=== INITIAL SSO CONFIG FETCH END ===");
    };

    fetchSSOConfig();
  }, [accessToken]);

  const handleMemberUpdateOk = () => {
    setIsUpdateModalModalVisible(false);
    memberForm.resetFields();
    form.resetFields();
  };

  const handleMemberOk = () => {
    setIsAddMemberModalVisible(false);
    memberForm.resetFields();
    form.resetFields();
  };

  const handleAdminOk = () => {
    setIsAddAdminModalVisible(false);
    memberForm.resetFields();
    form.resetFields();
  };

  const handleMemberCancel = () => {
    setIsAddMemberModalVisible(false);
    memberForm.resetFields();
    form.resetFields();
  };

  const handleAdminCancel = () => {
    setIsAddAdminModalVisible(false);
    setIsInvitationLinkModalVisible(false);
    memberForm.resetFields();
    form.resetFields();
  };

  const handleMemberUpdateCancel = () => {
    setIsUpdateModalModalVisible(false);
    memberForm.resetFields();
    form.resetFields();
  };
  // Define the type for the handleMemberCreate function
  type HandleMemberCreate = (formValues: Record<string, any>) => Promise<void>;

  const addMemberForm = (handleMemberCreate: HandleMemberCreate) => {
    return (
      <Form
        form={form}
        onFinish={handleMemberCreate}
        labelCol={{ span: 8 }}
        wrapperCol={{ span: 16 }}
        labelAlign="left"
      >
        <>
          <Form.Item label="Email" name="user_email" className="mb-8 mt-4">
            <Input
              name="user_email"
              className="px-3 py-2 border rounded-md w-full"
            />
          </Form.Item>
        </>
        <div style={{ textAlign: "right", marginTop: "10px" }} className="mt-4">
          <Button2 htmlType="submit">Add member</Button2>
        </div>
      </Form>
    );
  };

  const modifyMemberForm = (
    handleMemberUpdate: HandleMemberCreate,
    currentRole: string,
    userID: string
  ) => {
    return (
      <Form
        form={form}
        onFinish={handleMemberUpdate}
        labelCol={{ span: 8 }}
        wrapperCol={{ span: 16 }}
        labelAlign="left"
      >
        <>
          <Form.Item
            rules={[{ required: true, message: "Required" }]}
            label="User Role"
            name="user_role"
            labelCol={{ span: 10 }}
            labelAlign="left"
          >
            <Select value={currentRole}>
              {roles.map((role, index) => (
                <SelectItem key={index} value={role}>
                  {role}
                </SelectItem>
              ))}
            </Select>
          </Form.Item>
          <Form.Item
            label="Team ID"
            name="user_id"
            hidden={true}
            initialValue={userID}
            valuePropName="user_id"
            className="mt-8"
          >
            <Input value={userID} disabled />
          </Form.Item>
        </>
        <div style={{ textAlign: "right", marginTop: "10px" }}>
          <Button2 htmlType="submit">Update role</Button2>
        </div>
      </Form>
    );
  };

  const handleMemberUpdate = async (formValues: Record<string, any>) => {
    try {
      if (accessToken != null && admins != null) {
        message.info("Making API Call");
        const response: any = await userUpdateUserCall(
          accessToken,
          formValues,
          null
        );
        console.log(`response for team create call: ${response}`);
        // Checking if the team exists in the list and updating or adding accordingly
        const foundIndex = admins.findIndex((user) => {
          console.log(
            `user.user_id=${user.user_id}; response.user_id=${response.user_id}`
          );
          return user.user_id === response.user_id;
        });
        console.log(`foundIndex: ${foundIndex}`);
        if (foundIndex == -1) {
          console.log(`updates admin with new user`);
          admins.push(response);
          // If new user is found, update it
          setAdmins(admins); // Set the new state
        }
        message.success("Refresh tab to see updated user role");
        setIsUpdateModalModalVisible(false);
      }
    } catch (error) {
      console.error("Error creating the key:", error);
    }
  };

  const handleMemberCreate = async (formValues: Record<string, any>) => {
    try {
      if (accessToken != null && admins != null) {
        message.info("Making API Call");
        const response: any = await userUpdateUserCall(
          accessToken,
          formValues,
          "proxy_admin_viewer"
        );
        console.log(`response for team create call: ${response}`);
        // Checking if the team exists in the list and updating or adding accordingly

        // Give admin an invite link for inviting user to proxy
        const user_id = response.data?.user_id || response.user_id;
        invitationCreateCall(accessToken, user_id).then((data) => {
          setInvitationLinkData(data);
          setIsInvitationLinkModalVisible(true);
        });

        const foundIndex = admins.findIndex((user) => {
          console.log(
            `user.user_id=${user.user_id}; response.user_id=${response.user_id}`
          );
          return user.user_id === response.user_id;
        });
        console.log(`foundIndex: ${foundIndex}`);
        if (foundIndex == -1) {
          console.log(`updates admin with new user`);
          admins.push(response);
          // If new user is found, update it
          setAdmins(admins); // Set the new state
        }
        form.resetFields();
        setIsAddMemberModalVisible(false);
      }
    } catch (error) {
      console.error("Error creating the key:", error);
    }
  };
  const handleAdminCreate = async (formValues: Record<string, any>) => {
    try {
      if (accessToken != null && admins != null) {
        message.info("Making API Call");
        const user_role: Member = {
          role: "user",
          user_email: formValues.user_email,
          user_id: formValues.user_id,
        };
        const response: any = await userUpdateUserCall(
          accessToken,
          formValues,
          "proxy_admin"
        );

        // Give admin an invite link for inviting user to proxy
        const user_id = response.data?.user_id || response.user_id;
        invitationCreateCall(accessToken, user_id).then((data) => {
          setInvitationLinkData(data);
          setIsInvitationLinkModalVisible(true);
        });
        console.log(`response for team create call: ${response}`);
        // Checking if the team exists in the list and updating or adding accordingly
        const foundIndex = admins.findIndex((user) => {
          console.log(
            `user.user_id=${user.user_id}; response.user_id=${user_id}`
          );
          return user.user_id === response.user_id;
        });
        console.log(`foundIndex: ${foundIndex}`);
        if (foundIndex == -1) {
          console.log(`updates admin with new user`);
          admins.push(response);
          // If new user is found, update it
          setAdmins(admins); // Set the new state
        }
        form.resetFields();
        setIsAddAdminModalVisible(false);
      }
    } catch (error) {
      console.error("Error creating the key:", error);
    }
  };

  const handleSSOUpdate = async (formValues: Record<string, any>) => {
    console.log("=== HANDLE SSO UPDATE START ===");
    console.log("Raw form values received:", JSON.stringify(formValues, null, 2));
    
    if (accessToken == null) {
      console.log("ERROR: No access token available");
      return;
    }

    try {
      // Build the config object for the API
      const config: any = {
        sso_provider: formValues.sso_provider,
        proxy_base_url: formValues.proxy_base_url,
        user_email: formValues.user_email,
      };
      
      console.log("Initial config object:", JSON.stringify(config, null, 2));

      // Add provider-specific fields
      const provider = formValues.sso_provider;
      console.log("Selected provider:", provider);
      
      const providerConfig = ssoProviderConfigs[provider];
      console.log("Provider config from ssoProviderConfigs:", JSON.stringify(providerConfig, null, 2));
      
      if (providerConfig) {
        console.log("Processing provider-specific fields...");
        Object.entries(providerConfig.envVarMap).forEach(([formKey, envKey]) => {
          const value = formValues[formKey];
          console.log(`Processing field: ${formKey} -> ${envKey}, value: "${value}"`);
          
          // Only include fields that have values, aren't empty strings, and aren't masked secrets
          if (value && value.trim() !== '' && value !== '***') {
            config[formKey] = value;
            console.log(`Added to config: ${formKey} = "${value}"`);
          } else {
            console.log(`Skipped field ${formKey}: value is empty, masked, or undefined`);
          }
          // Note: If the value is '***' or empty, we don't include it in the config
          // This preserves the existing value on the server side
        });
      } else {
        console.log("ERROR: No provider config found for provider:", provider);
      }

      console.log("Final config object to send:", JSON.stringify(config, null, 2));

      // Call the new API endpoint
      console.log("Calling updateSSOProviderConfig API...");
      const response = await updateSSOProviderConfig(accessToken, config);
      console.log("API response:", JSON.stringify(response, null, 2));
      
      if (response?.status === 'success') {
        console.log("SSO config updated successfully");
        message.success('SSO configuration updated successfully');
        
        // Refresh the SSO config and update localStorage
        console.log("Refreshing SSO config from server...");
        const updatedConfig = await getSSOProviderConfig(accessToken);
        console.log("Fresh config from server:", JSON.stringify(updatedConfig, null, 2));
        
        if (updatedConfig?.config) {
          setSSOConfig(updatedConfig.config);
          // Update localStorage
          localStorage.setItem('litellm_sso_config', JSON.stringify(updatedConfig.config));
          console.log("Updated local SSO config state and localStorage");
        } else {
          console.log("WARNING: No config in fresh response");
        }
      } else {
        console.log("ERROR: API response indicates failure:", response);
      }
    } catch (error) {
      console.error("ERROR in handleSSOUpdate:", error);
      console.error("Error details:", JSON.stringify(error, null, 2));
      message.error(`Failed to update SSO configuration: ${error}`);
    }
    
    console.log("=== HANDLE SSO UPDATE END ===");
  };

  const handleShowAddSSOModal = async () => {
    console.log("=== HANDLE SHOW ADD SSO MODAL START ===");
    
    if (premiumUser !== true) {
      console.log("ERROR: User is not premium, showing error message");
      message.error("Only premium users can add SSO");
      return;
    }

    // Reset form first
    console.log("Resetting form fields...");
    form.resetFields();

    // Get the most current SSO configuration
    let currentSSOConfig = ssoConfig;
    
    // Always try to fetch fresh SSO configuration when opening the modal
    if (accessToken) {
      try {
        console.log("Fetching fresh SSO configuration...");
        const response = await getSSOProviderConfig(accessToken);
        console.log("Fresh SSO config API response:", JSON.stringify(response, null, 2));
        
        if (response?.config) {
          currentSSOConfig = response.config;
          setSSOConfig(currentSSOConfig);
          // Update localStorage
          localStorage.setItem('litellm_sso_config', JSON.stringify(currentSSOConfig));
          console.log("Fresh SSO Config fetched and stored:", JSON.stringify(currentSSOConfig, null, 2));
        } else {
          console.log("No config found in API response, using existing state");
          currentSSOConfig = ssoConfig;
        }
      } catch (error) {
        console.error("Failed to fetch fresh SSO config:", error);
        console.error("Error details:", JSON.stringify(error, null, 2));
        // Use existing ssoConfig and try localStorage as fallback
        if (!currentSSOConfig) {
          const storedConfig = localStorage.getItem('litellm_sso_config');
          if (storedConfig) {
            try {
              currentSSOConfig = JSON.parse(storedConfig);
              console.log("Using stored config as fallback:", JSON.stringify(currentSSOConfig, null, 2));
            } catch (e) {
              console.error("Failed to parse stored config:", e);
            }
          }
        }
      }
    } else {
      console.log("No access token available, using existing/stored config");
      // Try localStorage if no current config
      if (!currentSSOConfig) {
        const storedConfig = localStorage.getItem('litellm_sso_config');
        if (storedConfig) {
          try {
            currentSSOConfig = JSON.parse(storedConfig);
            console.log("Using stored config (no token):", JSON.stringify(currentSSOConfig, null, 2));
          } catch (e) {
            console.error("Failed to parse stored config:", e);
          }
        }
      }
    }

    // Pre-populate form with the most current SSO config
    if (currentSSOConfig) {
      console.log("=== FORM PRE-POPULATION LOGIC START ===");
      console.log("Pre-populating form with config:", JSON.stringify(currentSSOConfig, null, 2));
      
      const formData = buildFormDataFromConfig(currentSSOConfig);
      
      console.log("Final form data to set:", JSON.stringify(formData, null, 2));

      // Set form values with a delay to ensure the modal is fully rendered
      setTimeout(() => {
        console.log("=== SETTING FORM VALUES ===");
        console.log("Setting form values after timeout with:", JSON.stringify(formData, null, 2));
        try {
          form.setFieldsValue(formData);
          console.log("Form.setFieldsValue() called successfully");
          
          // Verify form values were set correctly
          setTimeout(() => {
            const actualValues = form.getFieldsValue();
            console.log("=== FORM VALUES VERIFICATION ===");
            console.log("Form values after setting (verification):", JSON.stringify(actualValues, null, 2));
            
            // Check if each expected field was set
            Object.keys(formData).forEach(key => {
              const expected = formData[key];
              const actual = actualValues[key];
              if (expected !== actual) {
                console.warn(`Mismatch for ${key}: expected "${expected}", got "${actual}"`);
              } else {
                console.log(`✓ ${key}: correctly set to "${actual}"`);
              }
            });
            console.log("=== FORM VALUES VERIFICATION END ===");
          }, 100);
        } catch (error) {
          console.error("Error setting form values:", error);
          console.error("Error details:", JSON.stringify(error, null, 2));
        }
        console.log("=== SETTING FORM VALUES END ===");
      }, 200);
      
      console.log("=== FORM PRE-POPULATION LOGIC END ===");
    } else {
      console.log("No currentSSOConfig available, not pre-populating form");
    }

    console.log("Opening SSO modal...");
    setIsAddSSOModalVisible(true);
    console.log("=== HANDLE SHOW ADD SSO MODAL END ===");
  };

  // Helper method to build form data from SSO config
  const buildFormDataFromConfig = (config: any) => {
    console.log("=== BUILD FORM DATA FROM CONFIG START ===");
    
    let providerToShow = null;
    const formData: any = {};
    
    // Always set basic fields if they exist
    if (config?.proxy_base_url) {
      formData.proxy_base_url = config.proxy_base_url;
      console.log("Set proxy_base_url from config:", config.proxy_base_url);
    }
    
    if (config?.user_email) {
      formData.user_email = config.user_email;
      console.log("Set user_email from config:", config.user_email);
    }
    
    console.log("Basic form data with proxy_base_url and user_email:", JSON.stringify(formData, null, 2));

    // First, check if there's an explicitly set SSO provider from config
    if (config?.sso_provider) {
      providerToShow = config.sso_provider;
      console.log("Found explicit SSO provider from config:", providerToShow);
    } else {
      console.log("No explicit SSO provider in config, checking for configured providers...");
      // Otherwise, find the first configured provider (one with actual values)
      if (config?.google?.google_client_id) {
        providerToShow = 'google';
        console.log("Found configured Google provider from config");
      } else if (config?.microsoft?.microsoft_client_id) {
        providerToShow = 'microsoft';
        console.log("Found configured Microsoft provider from config");
      } else if (config?.generic?.generic_client_id) {
        providerToShow = 'generic';
        console.log("Found configured Generic provider from config");
      } else {
        console.log("No configured providers found in config");
      }
    }

    console.log("Provider to show:", providerToShow);

    if (providerToShow) {
      formData.sso_provider = providerToShow;
      console.log("Set sso_provider in formData:", providerToShow);

      // Add provider-specific fields based on the provider to show
      if (providerToShow === 'google' && config?.google) {
        console.log("Processing Google provider config:", JSON.stringify(config.google, null, 2));
        
        if (config.google.google_client_id) {
          formData.google_client_id = config.google.google_client_id;
          console.log("Set google_client_id from config:", config.google.google_client_id);
        }
        // Set masked secrets to indicate they exist
        if (config.google.google_client_secret) {
          formData.google_client_secret = config.google.google_client_secret; // This will be '***'
          console.log("Set google_client_secret from config:", config.google.google_client_secret);
        }
      } else if (providerToShow === 'microsoft' && config?.microsoft) {
        console.log("Processing Microsoft provider config:", JSON.stringify(config.microsoft, null, 2));
        
        if (config.microsoft.microsoft_client_id) {
          formData.microsoft_client_id = config.microsoft.microsoft_client_id;
          console.log("Set microsoft_client_id from config:", config.microsoft.microsoft_client_id);
        }
        if (config.microsoft.microsoft_tenant) {
          formData.microsoft_tenant = config.microsoft.microsoft_tenant;
          console.log("Set microsoft_tenant from config:", config.microsoft.microsoft_tenant);
        }
        // Set masked secrets to indicate they exist
        if (config.microsoft.microsoft_client_secret) {
          formData.microsoft_client_secret = config.microsoft.microsoft_client_secret; // This will be '***'
          console.log("Set microsoft_client_secret from config:", config.microsoft.microsoft_client_secret);
        }
      } else if ((providerToShow === 'generic' || providerToShow === 'okta') && config?.generic) {
        console.log("Processing Generic/Okta provider config:", JSON.stringify(config.generic, null, 2));
        
        if (config.generic.generic_client_id) {
          formData.generic_client_id = config.generic.generic_client_id;
          console.log("Set generic_client_id from config:", config.generic.generic_client_id);
        }
        if (config.generic.generic_authorization_endpoint) {
          formData.generic_authorization_endpoint = config.generic.generic_authorization_endpoint;
          console.log("Set generic_authorization_endpoint from config:", config.generic.generic_authorization_endpoint);
        }
        if (config.generic.generic_token_endpoint) {
          formData.generic_token_endpoint = config.generic.generic_token_endpoint;
          console.log("Set generic_token_endpoint from config:", config.generic.generic_token_endpoint);
        }
        if (config.generic.generic_userinfo_endpoint) {
          formData.generic_userinfo_endpoint = config.generic.generic_userinfo_endpoint;
          console.log("Set generic_userinfo_endpoint from config:", config.generic.generic_userinfo_endpoint);
        }
        if (config.generic.generic_scope) {
          formData.generic_scope = config.generic.generic_scope;
          console.log("Set generic_scope from config:", config.generic.generic_scope);
        }
        // Set masked secrets to indicate they exist
        if (config.generic.generic_client_secret) {
          formData.generic_client_secret = config.generic.generic_client_secret; // This will be '***'
          console.log("Set generic_client_secret from config:", config.generic.generic_client_secret);
        }
      }
    }

    console.log("=== BUILD FORM DATA FROM CONFIG END ===");
    return formData;
  };

  const handleDeleteSSO = async () => {
    if (accessToken == null) {
      return;
    }

    Modal.confirm({
      title: 'Delete SSO Configuration',
      content: 'Are you sure you want to delete the SSO configuration? This will remove all SSO settings.',
      onOk: async () => {
        try {
          const response = await deleteSSOProviderConfig(accessToken);
          
          if (response?.status === 'success') {
            message.success('SSO configuration deleted successfully');
            setSSOConfig(null);
            // Clear localStorage
            localStorage.removeItem('litellm_sso_config');
            form.resetFields();
            setIsAddSSOModalVisible(false);
          }
        } catch (error) {
          console.error("Error deleting SSO config:", error);
          message.error(`Failed to delete SSO configuration: ${error}`);
        }
      },
    });
  };

  console.log(`admins: ${admins?.length}`);
  console.log("=== CURRENT STATE DEBUG ===");
  console.log("Current ssoConfig state:", JSON.stringify(ssoConfig, null, 2));
  
  // More detailed checking of SSO configuration
  const hasGoogleConfig = !!(ssoConfig?.google?.google_client_id);
  const hasMicrosoftConfig = !!(ssoConfig?.microsoft?.microsoft_client_id);
  const hasGenericConfig = !!(ssoConfig?.generic?.generic_client_id);
  const hasExplicitProvider = !!ssoConfig?.sso_provider;
  const hasProxyBaseUrl = !!ssoConfig?.proxy_base_url;
  const hasUserEmail = !!ssoConfig?.user_email;
  
  const isSSOConfigured = hasGoogleConfig || hasMicrosoftConfig || hasGenericConfig || hasExplicitProvider;
  
  console.log("SSO Configuration Analysis:");
  console.log("  - Has Google config (GOOGLE_CLIENT_ID):", hasGoogleConfig);
  console.log("  - Has Microsoft config (MICROSOFT_CLIENT_ID):", hasMicrosoftConfig);
  console.log("  - Has Generic config (GENERIC_CLIENT_ID):", hasGenericConfig);
  console.log("  - Has explicit SSO provider (SSO_PROVIDER):", hasExplicitProvider);
  console.log("  - Has proxy base URL (PROXY_BASE_URL):", hasProxyBaseUrl);
  console.log("  - Has user email (ADMIN_USER_EMAIL):", hasUserEmail);
  console.log("  - Is SSO configured overall:", isSSOConfigured);
  
  if (isSSOConfigured) {
    console.log("SSO Provider details:");
    if (ssoConfig?.sso_provider) {
      console.log("  - Provider type:", ssoConfig.sso_provider);
    }
    if (hasGoogleConfig) {
      console.log("  - Google Client ID:", ssoConfig?.google?.google_client_id);
      console.log("  - Google Client Secret:", ssoConfig?.google?.google_client_secret ? "[MASKED]" : "Not set");
    }
    if (hasMicrosoftConfig) {
      console.log("  - Microsoft Client ID:", ssoConfig?.microsoft?.microsoft_client_id);
      console.log("  - Microsoft Tenant:", ssoConfig?.microsoft?.microsoft_tenant);
      console.log("  - Microsoft Client Secret:", ssoConfig?.microsoft?.microsoft_client_secret ? "[MASKED]" : "Not set");
    }
    if (hasGenericConfig) {
      console.log("  - Generic Client ID:", ssoConfig?.generic?.generic_client_id);
      console.log("  - Generic Auth Endpoint:", ssoConfig?.generic?.generic_authorization_endpoint);
      console.log("  - Generic Token Endpoint:", ssoConfig?.generic?.generic_token_endpoint);
      console.log("  - Generic UserInfo Endpoint:", ssoConfig?.generic?.generic_userinfo_endpoint);
      console.log("  - Generic Scope:", ssoConfig?.generic?.generic_scope);
      console.log("  - Generic Client Secret:", ssoConfig?.generic?.generic_client_secret ? "[MASKED]" : "Not set");
    }
  }
  
  console.log("=== CURRENT STATE DEBUG END ===");
  
  // Utility function for debugging SSO config persistence
  const debugSSOConfigPersistence = () => {
    console.log("=== SSO CONFIG PERSISTENCE DEBUG ===");
    console.log("Current ssoConfig state:", JSON.stringify(ssoConfig, null, 2));
    
    const storedConfig = localStorage.getItem('litellm_sso_config');
    if (storedConfig) {
      try {
        const parsedConfig = JSON.parse(storedConfig);
        console.log("Stored config in localStorage:", JSON.stringify(parsedConfig, null, 2));
        console.log("State and storage match:", JSON.stringify(ssoConfig) === JSON.stringify(parsedConfig));
      } catch (e) {
        console.error("Failed to parse stored config:", e);
      }
    } else {
      console.log("No config found in localStorage");
    }
    
    console.log("Form current values:", JSON.stringify(form.getFieldsValue(), null, 2));
    console.log("=== SSO CONFIG PERSISTENCE DEBUG END ===");
  };

  // Call debug function periodically in development
  React.useEffect(() => {
    if (process.env.NODE_ENV === "development") {
      const interval = setInterval(debugSSOConfigPersistence, 10000); // Debug every 10 seconds
      return () => clearInterval(interval);
    }
  }, [ssoConfig]);
  
  return (
    <div className="w-full m-2 mt-2 p-8">
      <Title level={4}>Admin Access </Title>
      <Paragraph>Go to &apos;Internal Users&apos; page to add other admins.</Paragraph>
      <TabGroup>
        <TabList>
          <Tab>Security Settings</Tab>
          <Tab>SCIM</Tab>
        </TabList>
        <TabPanels>
          <TabPanel>
            <Card>
              <Title level={4}> ✨ Security Settings</Title>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '1rem' }}>
                <div>
                  <Button onClick={handleShowAddSSOModal}>
                    {(() => {
                      // Calculate SSO configuration status
                      const hasGoogleConfig = !!(ssoConfig?.google?.google_client_id);
                      const hasMicrosoftConfig = !!(ssoConfig?.microsoft?.microsoft_client_id);
                      const hasGenericConfig = !!(ssoConfig?.generic?.generic_client_id);
                      const hasExplicitProvider = !!ssoConfig?.sso_provider;
                      const isSSOConfigured = hasGoogleConfig || hasMicrosoftConfig || hasGenericConfig || hasExplicitProvider;
                      
                      if (isSSOConfigured) {
                        // Determine which provider is configured
                        let providerName = 'SSO';
                        
                        if (ssoConfig?.sso_provider) {
                          // Use explicit provider name if set
                          providerName = ssoConfig.sso_provider.charAt(0).toUpperCase() + ssoConfig.sso_provider.slice(1);
                        } else if (hasGoogleConfig) {
                          providerName = 'Google';
                        } else if (hasMicrosoftConfig) {
                          providerName = 'Microsoft';
                        } else if (hasGenericConfig) {
                          providerName = 'Generic';
                        }
                        
                        return `${providerName} SSO Configured`;
                      } else {
                        return 'Add SSO';
                      }
                    })()}
                  </Button>
                </div>
                <div>
                  <Button onClick={handleShowAllowedIPs}>Allowed IPs</Button>
                </div>
              </div>
            </Card>
           
            <div className="flex justify-start mb-4">
              <SSOModals
                isAddSSOModalVisible={isAddSSOModalVisible}
                isInstructionsModalVisible={isInstructionsModalVisible}
                handleAddSSOOk={handleAddSSOOk}
                handleAddSSOCancel={handleAddSSOCancel}
                handleShowInstructions={handleShowInstructions}
                handleInstructionsOk={handleInstructionsOk}
                handleInstructionsCancel={handleInstructionsCancel}
                handleDeleteSSO={handleDeleteSSO}
                isConfigured={!!(ssoConfig && (
                  (ssoConfig.google && ssoConfig.google.google_client_id) ||
                  (ssoConfig.microsoft && ssoConfig.microsoft.microsoft_client_id) ||
                  (ssoConfig.generic && ssoConfig.generic.generic_client_id) ||
                  ssoConfig.sso_provider
                ))}
                form={form}
              />
              <Modal
              title="Manage Allowed IP Addresses"
              width={800}
              visible={isAllowedIPModalVisible}
              onCancel={() => setIsAllowedIPModalVisible(false)}
              footer={[
                <Button className="mx-1"key="add" onClick={() => setIsAddIPModalVisible(true)}>
                  Add IP Address
                </Button>,
                <Button key="close" onClick={() => setIsAllowedIPModalVisible(false)}>
                  Close
                </Button>
              ]}
            >
              <Table>
  <TableHead>
    <TableRow>
      <TableHeaderCell>IP Address</TableHeaderCell>
      <TableHeaderCell className="text-right">Action</TableHeaderCell>
    </TableRow>
  </TableHead>
  <TableBody>
  {allowedIPs.map((ip, index) => (
  <TableRow key={index}>
    <TableCell>{ip}</TableCell>
    <TableCell className="text-right">
      {ip !== all_ip_address_allowed && (
        <Button onClick={() => handleDeleteIP(ip)} color="red" size="xs">
          Delete
        </Button>
      )}
    </TableCell>
  </TableRow>
))}
  </TableBody>
</Table>
        </Modal>

        <Modal
          title="Add Allowed IP Address"
          visible={isAddIPModalVisible}
          onCancel={() => setIsAddIPModalVisible(false)}
          footer={null}
        >
          <Form onFinish={handleAddIP}>
            <Form.Item
              name="ip"
              rules={[{ required: true, message: 'Please enter an IP address' }]}
            >
              <Input placeholder="Enter IP address" />
            </Form.Item>
            <Form.Item>
              <Button2 htmlType="submit">
                Add IP Address
              </Button2>
            </Form.Item>
          </Form>
        </Modal>

        <Modal
          title="Confirm Delete"
          visible={isDeleteIPModalVisible}
          onCancel={() => setIsDeleteIPModalVisible(false)}
          onOk={confirmDeleteIP}
          footer={[
            <Button className="mx-1"key="delete" onClick={() => confirmDeleteIP()}>
              Yes
            </Button>,
            <Button key="close" onClick={() => setIsDeleteIPModalVisible(false)}>
              Close
            </Button>
          ]}
        >
          <p>Are you sure you want to delete the IP address: {ipToDelete}?</p>
        </Modal>
        </div>
        <Callout title="Login without SSO" color="teal">
          If you need to login without sso, you can access{" "}
          <a href={nonSssoUrl} target="_blank">
            <b>{nonSssoUrl}</b>{" "}
          </a>
        </Callout>
          </TabPanel>
          <TabPanel>
            <SCIMConfig 
              accessToken={accessToken} 
              userID={userID}
              proxySettings={proxySettings}
            />
          </TabPanel>
        </TabPanels>
      </TabGroup>
    </div>
  );
};

export default AdminPanel;

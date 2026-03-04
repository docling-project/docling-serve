import argparse
from common import sm_client, autoscaling_client, create_model, create_endpoint_config, INSTANCE_TYPES
from create_autoscaling import create_autoscaling


def deregister_scalable_target(endpoint_name):
    resource_id = 'endpoint/' + endpoint_name + '/variant/AllTraffic'
    print('Deregistering scalable target: ' + resource_id)
    try:
        autoscaling_client.deregister_scalable_target(
            ServiceNamespace='sagemaker',
            ResourceId=resource_id,
            ScalableDimension='sagemaker:variant:DesiredInstanceCount')
        print('Scalable target deregistered')
    except autoscaling_client.exceptions.ObjectNotFoundException:
        print('No scalable target found, skipping deregistration')


def update_endpoint(endpoint_name, endpoint_config_name):
    deregister_scalable_target(endpoint_name)
    print('Updating endpoint: ' + endpoint_name)
    update_endpoint_response = sm_client.update_endpoint(
        EndpointName=endpoint_name,
        EndpointConfigName=endpoint_config_name)
    print("Endpoint Arn: " + update_endpoint_response['EndpointArn'])
    return update_endpoint_response


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Update a SageMaker endpoint')
    parser.add_argument('--endpoint-name', type=str, required=True,
                        help='Name of the endpoint to update')
    parser.add_argument('--env', type=str, choices=['dev', 'prod'], required=True,
                        help='Environment (dev or prod)')
    parser.add_argument('--endpoint-config-name', type=str, default=None,
                        help='Name of existing endpoint config to use')
    parser.add_argument('--image-version', type=str, default=None,
                        help='Docker image version tag (required if endpoint-config-name is not provided, e.g. v1.13.1)')
    args = parser.parse_args()

    if args.endpoint_config_name:
        endpoint_config_name = args.endpoint_config_name
    else:
        if not args.image_version:
            parser.error('--image-version is required when --endpoint-config-name is not provided')
        model_name = create_model(args.image_version)
        endpoint_config_name = create_endpoint_config(model_name, INSTANCE_TYPES[args.env])

    update_endpoint_response = update_endpoint(args.endpoint_name, endpoint_config_name)
    print(update_endpoint_response)

    print('Waiting for {} endpoint to be in service...'.format(args.endpoint_name))
    waiter = sm_client.get_waiter('endpoint_in_service')
    waiter.wait(EndpointName=args.endpoint_name)
    create_autoscaling(args.endpoint_name)
